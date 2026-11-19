# -*- coding: utf-8 -*-
"""GPU 揽号引擎（全部 8 条链）

接口与 app/main.py 里的 EngineRunner 一致：
    start(chain, prefix, suffix, threads, count) / stop() / running
事件协议与 engine/vanity.js 一致：ready / progress / found / done / stopped / error

两条内核分支：
    EVM 5 条（eth/bsc/polygon/arbitrum/base）—— keccak256(公钥)[12:] → hex 匹配
    Base58 3 条（btc/doge/trx）—— P2PKH 或 TRON 派生 → Base58Check → 字符串匹配
是否走 GPU 由界面开关决定，默认 CPU。
"""

import ctypes as C
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GPU_DIR = os.path.join(ROOT, "gpu")
for _p in (HERE, GPU_DIR):
    if _p not in sys.path:
        sys.path.append(_p)

import opencl              # noqa: E402
from keccak_py import to_checksum   # noqa: E402

N_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

EVM_CHAINS = {"eth", "bsc", "polygon", "arbitrum", "base"}
# 链 id -> (内核 mode, 版本字节)
B58_CHAINS = {"btc": (0, 0x00), "doge": (1, 0x1E), "trx": (2, 0x41)}

HEX = "0123456789abcdef"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

SRC_FILES = ("keccak.cl", "secp256k1.cl", "sha256.cl", "ripemd160.cl",
             "base58.cl", "vanity.cl", "vanity_base58.cl")

# 每个 work-item 走 STEPS 步，CHUNK 步批量求逆一次
WORKERS = 4096
STEPS = 256
CHUNK = 8

# 多规则并行：内核里规则表的维度（与 vanity.cl / vanity_base58.cl 的宏保持一致）
MAX_RULES = 32
RULE_MAX = 40

_dev_cache = {}
_dev_lock = threading.Lock()


# ---------------------------------------------------------------- 能力探测

def gpu_available():
    try:
        return bool(opencl.list_devices())
    except Exception:
        return False


def gpu_summary():
    try:
        devs = opencl.list_devices()
        if not devs:
            return None
        d = devs[0]
        return {"name": d["device"], "cu": d["cu"], "mem_mb": d["mem_mb"]}
    except Exception:
        return None


def gpu_chains():
    """GPU 支持的链集合"""
    return set(EVM_CHAINS) | set(B58_CHAINS)


def _get_device():
    with _dev_lock:
        if "dev" in _dev_cache:
            return _dev_cache["dev"]
        dev = opencl.Device()
        src = ""
        for f in SRC_FILES:
            with open(os.path.join(GPU_DIR, f), "r", encoding="utf-8") as fh:
                src += "\n" + fh.read()
        dev.build(src, ["vanity_evm", "vanity_base58"])
        _dev_cache["dev"] = dev
        return dev


# ---------------------------------------------------------------- 引擎

class GpuRunner:
    def __init__(self, on_event):
        self.on_event = on_event
        self._thread = None
        self._stop = threading.Event()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, chain, prefix, suffix, threads, count, rules=None):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(chain, prefix, suffix, int(count), rules), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ---------------- 内部

    def _loop(self, chain, prefix, suffix, count, rules=None):
        try:
            self._run(chain, prefix, suffix, count, rules)
        except Exception as exc:                      # noqa: BLE001
            self.on_event({"t": "error", "message": f"GPU 引擎出错：{exc}"})

    def _run(self, chain, prefix, suffix, count, rules=None):
        is_evm = chain in EVM_CHAINS
        if is_evm:
            alphabet, unit, mode, ver = HEX, "hex", 0, 0
        elif chain in B58_CHAINS:
            mode, ver = B58_CHAINS[chain]
            alphabet, unit = B58, "base58"
        else:
            self.on_event({"t": "error", "message": f"GPU 不支持该链：{chain}"})
            return

        # 规则集合：没传就用单条 prefix/suffix，传了就用多规则（最多 8 条）
        if rules:
            rule_list = [{"prefix": str(r.get("prefix", "")),
                          "suffix": str(r.get("suffix", ""))} for r in rules][:MAX_RULES]
        else:
            rule_list = [{"prefix": prefix, "suffix": suffix}]

        for r in rule_list:
            if is_evm:
                r["prefix"] = r["prefix"].lower().replace("0x", "")
                r["suffix"] = r["suffix"].lower()
            else:
                r["prefix"] = r["prefix"].strip()
                r["suffix"] = r["suffix"].strip()

        for r in rule_list:
            for ch in r["prefix"] + r["suffix"]:
                if ch not in alphabet:
                    self.on_event({"t": "error", "message": "@GPU_BAD_CHAR"})
                    return

        # 规则表：按 nibble（EVM）或 ASCII（Base58）扁平化到定长槽位
        pre_tbl = bytearray(MAX_RULES * RULE_MAX)
        suf_tbl = bytearray(MAX_RULES * RULE_MAX)
        plen_arr = [0] * MAX_RULES
        slen_arr = [0] * MAX_RULES
        for i, r in enumerate(rule_list):
            if is_evm:
                pb = bytes(HEX.index(c) for c in r["prefix"])
                sb = bytes(HEX.index(c) for c in r["suffix"])
            else:
                pb = r["prefix"].encode("ascii")
                sb = r["suffix"].encode("ascii")
            pre_tbl[i * RULE_MAX:i * RULE_MAX + len(pb)] = pb
            suf_tbl[i * RULE_MAX:i * RULE_MAX + len(sb)] = sb
            plen_arr[i] = len(pb)
            slen_arr[i] = len(sb)

        # 多规则并行：命中概率相加 → 期望次数 1 / Σ(1/单条期望)
        inverses = []
        for r in rule_list:
            fixed = len(r["prefix"]) + len(r["suffix"])
            inverses.append(1 / (len(alphabet) ** fixed) if fixed else 1.0)
        inv_sum = sum(inverses)
        target = max(1, int(round(1 / inv_sum))) if inv_sum > 0 else 1
        fixed_chars = max((len(r["prefix"]) + len(r["suffix"])) for r in rule_list)
        max_hits = max(64, count * 2)

        # 首次启用 GPU 要现场编译内核（NVIDIA 上约 2-4 分钟），先告诉界面别以为卡死
        if "dev" not in _dev_cache:
            self.on_event({"t": "building"})

        dev = _get_device()

        # 显存缓冲只分配一次（EVM 20 字节/命中，Base58 40 字节/命中）
        if "k0" not in dev.buffers:
            dev.buffer("k0", WORKERS * 32, opencl.CL_MEM_READ_ONLY)
            dev.buffer("rules_pre", MAX_RULES * RULE_MAX, opencl.CL_MEM_READ_ONLY)
            dev.buffer("rules_suf", MAX_RULES * RULE_MAX, opencl.CL_MEM_READ_ONLY)
            dev.buffer("rules_plen", MAX_RULES * 4, opencl.CL_MEM_READ_ONLY)
            dev.buffer("rules_slen", MAX_RULES * 4, opencl.CL_MEM_READ_ONLY)
            dev.buffer("hc", 16, opencl.CL_MEM_READ_WRITE)
            dev.buffer("meta", max_hits * 12, opencl.CL_MEM_WRITE_ONLY)
            dev.buffer("addr", max_hits * 20, opencl.CL_MEM_WRITE_ONLY)
            dev.buffer("addr58", max_hits * 40, opencl.CL_MEM_WRITE_ONLY)
            dev._max_hits = max_hits

        if max_hits > getattr(dev, "_max_hits", 0):
            for name, size in (("meta", max_hits * 12), ("addr", max_hits * 20),
                               ("addr58", max_hits * 40)):
                old = dev.buffers.pop(name, None)
                if old:
                    opencl.lib().clReleaseMemObject(old)
                dev.buffer(name, size, opencl.CL_MEM_WRITE_ONLY)
            dev._max_hits = max_hits

        PRE = (C.c_ubyte * (MAX_RULES * RULE_MAX))(*pre_tbl)
        SUF = (C.c_ubyte * (MAX_RULES * RULE_MAX))(*suf_tbl)
        PLEN = (C.c_int * MAX_RULES)(*plen_arr)
        SLEN = (C.c_int * MAX_RULES)(*slen_arr)
        dev.write("rules_pre", MAX_RULES * RULE_MAX, PRE)
        dev.write("rules_suf", MAX_RULES * RULE_MAX, SUF)
        dev.write("rules_plen", MAX_RULES * 4, PLEN)
        dev.write("rules_slen", MAX_RULES * 4, SLEN)

        K = (C.c_uint * (WORKERS * 8))()
        HC = (C.c_uint * 4)(0)
        META = (C.c_uint * (max_hits * 3))()
        ADDR = (C.c_ubyte * (max_hits * 20))()
        ADDR58 = (C.c_ubyte * (max_hits * 40))()
        HOST = (C.c_ubyte * (max_hits * 40))() if not is_evm else None

        self.on_event({
            "t": "ready",
            "threads": dev.info["cu"],
            "chain": chain,
            "chainTag": chain.upper(),
            "unit": unit,
            "target": target,
            "fixedChars": fixed_chars,
            "prefix": rule_list[0]["prefix"],
            "suffix": rule_list[0]["suffix"],
            "rules": rule_list,
            "ruleCount": len(rule_list),
            "count": count,
            "gpu": dev.info["device"],
        })

        attempts = 0
        collected = 0
        t0 = time.time()
        last_emit = 0.0

        while not self._stop.is_set() and collected < count:
            # 每批重新随机起点：覆盖互不重叠的私钥区间
            ks = []
            while len(ks) < WORKERS:
                v = int.from_bytes(os.urandom(32), "big")
                if 0 < v < N_ORDER - STEPS - 2:
                    ks.append(v)
            for i, v in enumerate(ks):
                for j in range(8):
                    K[i * 8 + j] = (v >> (32 * j)) & 0xFFFFFFFF
            dev.write("k0", WORKERS * 32, K)

            HC[0] = 0
            dev.write("hc", 4, HC)

            if is_evm:
                dev.run("vanity_evm", WORKERS, 32, [
                    ("k0",),
                    (C.sizeof(C.c_int), C.byref(C.c_int(STEPS))),
                    ("rules_pre",),
                    ("rules_suf",),
                    ("rules_plen",),
                    ("rules_slen",),
                    (C.sizeof(C.c_int), C.byref(C.c_int(len(rule_list)))),
                    ("hc",),
                    ("meta",),
                    ("addr",),
                    (C.sizeof(C.c_int), C.byref(C.c_int(max_hits))),
                    (C.sizeof(C.c_int), C.byref(C.c_int(CHUNK))),
                ])
            else:
                dev.run("vanity_base58", WORKERS, 32, [
                    ("k0",),
                    (C.sizeof(C.c_int), C.byref(C.c_int(STEPS))),
                    ("rules_pre",),
                    ("rules_suf",),
                    ("rules_plen",),
                    ("rules_slen",),
                    (C.sizeof(C.c_int), C.byref(C.c_int(len(rule_list)))),
                    ("hc",),
                    ("meta",),
                    ("addr58",),
                    (C.sizeof(C.c_int), C.byref(C.c_int(max_hits))),
                    (C.sizeof(C.c_int), C.byref(C.c_int(CHUNK))),
                    (C.sizeof(C.c_int), C.byref(C.c_int(mode))),
                    (C.sizeof(C.c_ubyte), C.byref(C.c_ubyte(ver))),
                ])
            dev.finish()

            dev.read("hc", 4, HC)
            got = min(HC[0], max_hits)
            if got:
                dev.read("meta", max_hits * 12, META)
                if is_evm:
                    dev.read("addr", max_hits * 20, ADDR)
                else:
                    dev.read("addr58", max_hits * 40, HOST)
                    for i in range(max_hits * 40):
                        ADDR58[i] = HOST[i]

            attempts += WORKERS * STEPS

            for i in range(got):
                if collected >= count or self._stop.is_set():
                    break
                wid = META[i * 3]
                off = META[i * 3 + 1]
                rule_index = int(META[i * 3 + 2])
                priv = (ks[wid] + off) % N_ORDER
                collected += 1

                if is_evm:
                    addr = bytes(ADDR[i * 20:(i + 1) * 20]).hex()
                    shown = to_checksum(addr)
                    match_key = addr
                else:
                    ln = ADDR58[i * 40]
                    shown = bytes(ADDR58[i * 40 + 1:i * 40 + 1 + ln]).decode("ascii", "replace")
                    match_key = shown

                elapsed = time.time() - t0
                rate = int(attempts / elapsed) if elapsed > 0 else 0

                self.on_event({
                    "t": "found",
                    "index": collected,
                    "count": count,
                    "address": shown,
                    "addressLower": shown if not is_evm else "0x" + shown,
                    "matchKey": match_key,
                    "privHex": hex(priv)[2:].zfill(64),
                    "ruleIndex": rule_index,
                    "attempts": attempts,
                    "elapsed": round(elapsed, 2),
                    "rate": rate,
                })

            elapsed = time.time() - t0
            rate = int(attempts / elapsed) if elapsed > 0 else 0

            if collected >= count:
                self.on_event({"t": "done", "collected": collected,
                               "attempts": attempts, "elapsed": round(elapsed, 2)})
                return

            if elapsed - last_emit >= 0.2:
                last_emit = elapsed
                remain = max(1, count - collected)
                eta = max(0, int((target * remain - attempts) / rate)) if rate > 0 else None
                self.on_event({
                    "t": "progress",
                    "attempts": attempts,
                    "rate": rate,
                    "elapsed": round(elapsed, 1),
                    "eta": eta,
                    "target": target,
                    "collected": collected,
                    "count": count,
                })

        self.on_event({"t": "stopped", "collected": collected})


if __name__ == "__main__":
    print(gpu_summary())
    r = GpuRunner(print)
    r.start("btc", "1", "", 0, 2)
    while r.running:
        time.sleep(0.3)

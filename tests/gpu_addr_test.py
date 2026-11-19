# -*- coding: utf-8 -*-
"""GPU 揽号内核正确性验证：GPU 算出的地址必须与 Node 用同一私钥派生的地址一致"""

import ctypes as C
import json
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))
import opencl  # noqa: E402

N_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
NODE = r"C:\Program Files\nodejs\node.exe"

WORKERS = 16
STEPS = 8
CHUNK = 8
CHUNKS = STEPS // CHUNK

random.seed(20261118)
k0 = [random.getrandbits(256) % (N_ORDER - 1000) + 1 for _ in range(WORKERS)]


def to_limbs(v):
    return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(8)]


# ---- GPU
dev = opencl.Device()
src = ""
for f in ("keccak.cl", "secp256k1.cl", "vanity.cl"):
    with open(os.path.join(ROOT, "gpu", f), "r", encoding="utf-8") as fh:
        src += "\n" + fh.read()
dev.build(src, ["vanity_evm"])

K = (C.c_uint * (WORKERS * 8))()
for i, v in enumerate(k0):
    for j, l in enumerate(to_limbs(v)):
        K[i * 8 + j] = l
dev.buffer("k0", WORKERS * 8 * 4, opencl.CL_MEM_READ_ONLY)
dev.write("k0", WORKERS * 8 * 4, K)

RMAX, RRULE = 8, 40
ZERO = (C.c_ubyte * (RMAX * RRULE))()
ZEROI = (C.c_int * RMAX)()
dev.buffer("rules_pre", RMAX * RRULE, opencl.CL_MEM_READ_ONLY)
dev.write("rules_pre", RMAX * RRULE, ZERO)
dev.buffer("rules_suf", RMAX * RRULE, opencl.CL_MEM_READ_ONLY)
dev.write("rules_suf", RMAX * RRULE, ZERO)
dev.buffer("rules_plen", RMAX * 4, opencl.CL_MEM_READ_ONLY)
dev.write("rules_plen", RMAX * 4, ZEROI)
dev.buffer("rules_slen", RMAX * 4, opencl.CL_MEM_READ_ONLY)
dev.write("rules_slen", RMAX * 4, ZEROI)

HIT_COUNT = (C.c_uint * 4)(0)
max_hits = WORKERS * STEPS
META = (C.c_uint * (max_hits * 3))()
ADDR = (C.c_ubyte * (max_hits * 20))()
dev.buffer("hc", 16, opencl.CL_MEM_READ_WRITE)
dev.write("hc", 4, HIT_COUNT)
dev.buffer("meta", max_hits * 12, opencl.CL_MEM_WRITE_ONLY)
dev.buffer("addr", max_hits * 20, opencl.CL_MEM_WRITE_ONLY)

dev.run("vanity_evm", WORKERS, 1, [
    ("k0",),
    (C.sizeof(C.c_int), C.byref(C.c_int(STEPS))),
    ("rules_pre",),
    ("rules_suf",),
    ("rules_plen",),
    ("rules_slen",),
    (C.sizeof(C.c_int), C.byref(C.c_int(1))),
    ("hc",),
    ("meta",),
    ("addr",),
    (C.sizeof(C.c_int), C.byref(C.c_int(max_hits))),
    (C.sizeof(C.c_int), C.byref(C.c_int(CHUNK))),
])
dev.finish()
dev.read("hc", 4, HIT_COUNT)
dev.read("meta", max_hits * 12, META)
dev.read("addr", max_hits * 20, ADDR)
dev.release()

got = HIT_COUNT[0]
print(f"命中 {got} 条（预期 {max_hits}）")

records = []
for i in range(min(got, max_hits)):
    wid = META[i * 3]
    off = META[i * 3 + 1]
    records.append((wid, off, bytes(ADDR[i * 20:(i + 1) * 20])))

# ---- Node 参考值
privs = []
for wid, off, _ in records:
    privs.append((k0[wid] + off) % N_ORDER)

js = """
const fs = require('node:fs');
const { EthKeyDeriver } = require(%s);
const d = new EthKeyDeriver();
const privs = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const out = privs.map(h => Buffer.from(d.derive(Buffer.from(h, 'hex'))).toString('hex'));
fs.writeFileSync(process.argv[2], JSON.stringify(out));
""" % json.dumps(os.path.join(ROOT, "engine", "eth.js"))

tmp = os.environ.get("TEMP", ".")
inp = os.path.join(tmp, "gpu_addr_in.json")
outp = os.path.join(tmp, "gpu_addr_out.json")
with open(inp, "w", encoding="utf-8") as fh:
    json.dump([hex(p)[2:].zfill(64) for p in privs], fh)
res = subprocess.run([NODE, "-e", js, inp, outp], capture_output=True, text=True, encoding="utf-8")
if res.returncode != 0:
    print("node 失败:", res.stderr[:500])
    sys.exit(1)
with open(outp, "r", encoding="utf-8") as fh:
    refs = json.load(fh)

fails = 0
for i, (wid, off, addr) in enumerate(records):
    if addr.hex() != refs[i]:
        fails += 1
        if fails <= 3:
            print(f"不一致 wid={wid} off={off} gpu={addr.hex()} ref={refs[i]}")

print(f"地址对拍: {len(records) - fails}/{len(records)} 一致")
print("RESULT:", "PASS" if fails == 0 and got == max_hits else "FAIL")
sys.exit(0 if fails == 0 and got == max_hits else 1)

# -*- coding: utf-8 -*-
"""GPU 哈希内核对拍：SHA-256 / 双 SHA-256 / RIPEMD-160 / Base58 编码

运行：C:\\Python314\\python.exe tests\\gpu_hash_test.py
"""

import ctypes as C
import hashlib
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))

import opencl  # noqa: E402

ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b):
    z = 0
    while z < len(b) and b[z] == 0:
        z += 1
    n = int.from_bytes(b, "big")
    s = ""
    while n > 0:
        n, r = divmod(n, 58)
        s = ALPH[r] + s
    return "1" * z + s


def load_src(names):
    out = ""
    for f in names:
        with open(os.path.join(ROOT, "gpu", f), "r", encoding="utf-8") as fh:
            out += "\n" + fh.read()
    return out


print("OpenCL 设备：", opencl.list_devices()[0]["device"])

dev = opencl.Device()
dev.build(load_src(["keccak.cl", "secp256k1.cl", "sha256.cl", "ripemd160.cl", "base58.cl"]),
          ["test_sha256", "test_sha256d21", "test_ripemd160", "test_base58"],
          options=b"")

N = 64
random.seed(20261118)

ok = fail = 0

# ---------------- SHA-256（33 字节输入）
msgs = [bytes(random.getrandbits(8) for _ in range(33)) for _ in range(N)]
dev.buffer("s_in", N * 33, opencl.CL_MEM_READ_ONLY)
dev.buffer("s_out", N * 32, opencl.CL_MEM_WRITE_ONLY)
IN = (C.c_ubyte * (N * 33))(*b"".join(msgs))
dev.write("s_in", N * 33, IN)
dev.run("test_sha256", N, None, [("s_in",), ("s_out",)])
dev.finish()
OUT = (C.c_ubyte * (N * 32))()
dev.read("s_out", N * 32, OUT)
gpu = bytes(OUT)
for i in range(N):
    want = hashlib.sha256(msgs[i]).digest()
    got = gpu[i * 32:(i + 1) * 32]
    if want == got:
        ok += 1
    else:
        fail += 1
        if fail <= 3:
            print(f"  SHA256 不一致 #{i}: want={want.hex()} got={got.hex()}")
print(f"SHA-256(33B): {ok}/{N} 一致")

# ---------------- 双 SHA-256（21 字节输入）
ok2 = fail2 = 0
msgs2 = [bytes(random.getrandbits(8) for _ in range(21)) for _ in range(N)]
dev.buffer("d_in", N * 21, opencl.CL_MEM_READ_ONLY)
dev.buffer("d_out", N * 32, opencl.CL_MEM_WRITE_ONLY)
IN2 = (C.c_ubyte * (N * 21))(*b"".join(msgs2))
dev.write("d_in", N * 21, IN2)
dev.run("test_sha256d21", N, None, [("d_in",), ("d_out",)])
dev.finish()
OUT2 = (C.c_ubyte * (N * 32))()
dev.read("d_out", N * 32, OUT2)
gpu2 = bytes(OUT2)
for i in range(N):
    want = hashlib.sha256(hashlib.sha256(msgs2[i]).digest()).digest()
    got = gpu2[i * 32:(i + 1) * 32]
    if want == got:
        ok2 += 1
    else:
        fail2 += 1
        if fail2 <= 3:
            print(f"  双 SHA256 不一致 #{i}: want={want.hex()} got={got.hex()}")
print(f"双 SHA-256(21B): {ok2}/{N} 一致")

# ---------------- RIPEMD-160（32 字节输入）
ok3 = fail3 = 0
msgs3 = [bytes(random.getrandbits(8) for _ in range(32)) for _ in range(N)]
dev.buffer("r_in", N * 32, opencl.CL_MEM_READ_ONLY)
dev.buffer("r_out", N * 20, opencl.CL_MEM_WRITE_ONLY)
IN3 = (C.c_ubyte * (N * 32))(*b"".join(msgs3))
dev.write("r_in", N * 32, IN3)
dev.run("test_ripemd160", N, None, [("r_in",), ("r_out",)])
dev.finish()
OUT3 = (C.c_ubyte * (N * 20))()
dev.read("r_out", N * 20, OUT3)
gpu3 = bytes(OUT3)
for i in range(N):
    want = hashlib.new("ripemd160", msgs3[i]).digest()
    got = gpu3[i * 20:(i + 1) * 20]
    if want == got:
        ok3 += 1
    else:
        fail3 += 1
        if fail3 <= 3:
            print(f"  RIPEMD160 不一致 #{i}: want={want.hex()} got={got.hex()}")
print(f"RIPEMD-160(32B): {ok3}/{N} 一致")

# ---------------- Base58 编码（25 字节输入）
ok4 = fail4 = 0
raw = []
raw.append(bytes(25))                                   # 全零：应输出 25 个 '1'
for _ in range(N - 1):
    b = bytearray(random.getrandbits(8) for _ in range(25))
    if random.random() < 0.5:
        b[0] = 0                                        # 模拟 BTC 版本字节 0x00
    raw.append(bytes(b))

dev.buffer("b_in", N * 25, opencl.CL_MEM_READ_ONLY)
dev.buffer("b_out", N * 40, opencl.CL_MEM_WRITE_ONLY)
IN4 = (C.c_ubyte * (N * 25))(*b"".join(raw))
dev.write("b_in", N * 25, IN4)
dev.run("test_base58", N, None, [("b_in",), ("b_out",)])
dev.finish()
OUT4 = (C.c_ubyte * (N * 40))()
dev.read("b_out", N * 40, OUT4)
gpu4 = bytes(OUT4)
for i in range(N):
    ln = gpu4[i * 40]
    got = gpu4[i * 40 + 1:i * 40 + 1 + ln].decode("ascii", "replace")
    want = b58encode(raw[i])
    if got == want:
        ok4 += 1
    else:
        fail4 += 1
        if fail4 <= 3:
            print(f"  Base58 不一致 #{i}: want={want!r} got={got!r}")

print(f"Base58(25B): {ok4}/{N} 一致")

total_fail = fail + fail2 + fail3 + fail4
print()
print("RESULT:", "PASS" if total_fail == 0 else f"FAIL ({total_fail} 处不一致)")
sys.exit(0 if total_fail == 0 else 1)

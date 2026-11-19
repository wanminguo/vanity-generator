# -*- coding: utf-8 -*-
"""GPU Base58 链揽号内核对拍：BTC / DOGE / TRON 地址生成

固定私钥 → GPU 算 (k+1)·G → 派生地址，与纯 Python 参考实现逐条比对。

运行：C:\\Python314\\python.exe tests\\gpu_base58_e2e.py
"""

import ctypes as C
import hashlib
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))
sys.path.insert(0, os.path.join(ROOT, "app"))

import opencl  # noqa: E402
from keccak_py import keccak256  # noqa: E402

ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

P = 2 ** 256 - 2 ** 32 - 977
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


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


def add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    x1, y1 = p
    x2, y2 = q
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p == q:
        lam = 3 * x1 * x1 % P * pow(2 * y1, P - 2, P) % P
    else:
        lam = (y2 - y1) % P * pow((x2 - x1) % P, P - 2, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def mul(k):
    r = None
    b = (GX, GY)
    while k:
        if k & 1:
            r = add(r, b)
        b = add(b, b)
        k >>= 1
    return r


def ref_addr(k, mode, ver):
    pt = mul((k + 1) % (2 ** 256))
    x, y = pt
    xb = x.to_bytes(32, "big")
    yb = y.to_bytes(32, "big")
    if mode == 2:
        h20 = keccak256(xb + yb)[12:]
    else:
        cp = bytes([2 | (y & 1)]) + xb
        h20 = hashlib.new("ripemd160", hashlib.sha256(cp).digest()).digest()
    payload = bytes([ver]) + h20
    chk = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return b58encode(payload + chk)


def load_src(names):
    out = ""
    for f in names:
        with open(os.path.join(ROOT, "gpu", f), "r", encoding="utf-8") as fh:
            out += "\n" + fh.read()
    return out


print("OpenCL 设备：", opencl.list_devices()[0]["device"])

SRC = load_src(["keccak.cl", "secp256k1.cl", "sha256.cl", "ripemd160.cl",
                "base58.cl", "vanity.cl", "vanity_base58.cl"])

dev = opencl.Device()
dev.build(SRC, ["vanity_base58"], options=b"")

N = 32
STEP = 1
random.seed(20261118)
keys = [random.getrandbits(256) for _ in range(N)]

dev.buffer("k0", N * 32, opencl.CL_MEM_READ_ONLY)
K = (C.c_uint * (N * 8))()
for i, k in enumerate(keys):
    for w in range(8):
        K[i * 8 + w] = (k >> (32 * w)) & 0xFFFFFFFF
dev.write("k0", N * 32, K)

RMAX, RRULE = 8, 40
EMPTY = (C.c_ubyte * (RMAX * RRULE))()
EMPTYI = (C.c_int * RMAX)()
dev.buffer("rules_pre", RMAX * RRULE, opencl.CL_MEM_READ_ONLY)
dev.write("rules_pre", RMAX * RRULE, EMPTY)
dev.buffer("rules_suf", RMAX * RRULE, opencl.CL_MEM_READ_ONLY)
dev.write("rules_suf", RMAX * RRULE, EMPTY)
dev.buffer("rules_plen", RMAX * 4, opencl.CL_MEM_READ_ONLY)
dev.write("rules_plen", RMAX * 4, EMPTYI)
dev.buffer("rules_slen", RMAX * 4, opencl.CL_MEM_READ_ONLY)
dev.write("rules_slen", RMAX * 4, EMPTYI)

MAXH = N
dev.buffer("hit_count", 4, opencl.CL_MEM_READ_WRITE)
dev.buffer("hit_meta", MAXH * 3 * 4, opencl.CL_MEM_READ_WRITE)
dev.buffer("hit_addr", MAXH * 40, opencl.CL_MEM_READ_WRITE)

total_ok = total_bad = 0
cases = [("BTC", 0, 0x00), ("DOGE", 1, 0x1E), ("TRON", 2, 0x41)]

for label, mode, ver in cases:
    zero = (C.c_uint * 1)(0)
    dev.write("hit_count", 4, zero)
    meta0 = (C.c_uint * (MAXH * 3))()
    dev.write("hit_meta", MAXH * 3 * 4, meta0)
    a0 = (C.c_ubyte * (MAXH * 40))()
    dev.write("hit_addr", MAXH * 40, a0)

    mh = C.c_int(MAXH)
    cs = C.c_int(1)
    st = C.c_int(STEP)
    md = C.c_int(mode)
    vb = C.c_ubyte(ver)

    dev.run("vanity_base58", N, None, [
        ("k0",), (C.sizeof(C.c_int), C.byref(st)),
        ("rules_pre",), ("rules_suf",), ("rules_plen",), ("rules_slen",),
        (C.sizeof(C.c_int), C.byref(C.c_int(1))),
        ("hit_count",), ("hit_meta",), ("hit_addr",),
        (C.sizeof(C.c_int), C.byref(mh)),
        (C.sizeof(C.c_int), C.byref(cs)),
        (C.sizeof(C.c_int), C.byref(md)),
        (C.sizeof(C.c_ubyte), C.byref(vb)),
    ])
    dev.finish()

    cnt_buf = (C.c_uint * 1)()
    dev.read("hit_count", 4, cnt_buf)
    cnt = int(cnt_buf[0])
    addr_buf = (C.c_ubyte * (MAXH * 40))()
    dev.read("hit_addr", MAXH * 40, addr_buf)
    raw = bytes(addr_buf)

    ok = bad = 0
    for i in range(min(cnt, MAXH)):
        ln = raw[i * 40]
        got = raw[i * 40 + 1:i * 40 + 1 + ln].decode("ascii", "replace")
        want = ref_addr(keys[i], mode, ver)
        if got == want:
            ok += 1
        else:
            bad += 1
            if bad <= 2:
                print(f"  {label} 不一致 #{i}: want={want} got={got}")
    total_ok += ok
    total_bad += bad + (N - min(cnt, MAXH))
    print(f"{label}: 命中 {cnt}/{N}，地址一致 {ok}/{N}")

print()
print("RESULT:", "PASS" if total_bad == 0 else f"FAIL ({total_bad})")
sys.exit(0 if total_bad == 0 else 1)

# -*- coding: utf-8 -*-
"""小整数标量乘定点排查：k=1..8，用 Python 参考实现对照"""

import ctypes as C
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))
import opencl  # noqa: E402

MOD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def dbl(p):
    x, y = p
    lam = (3 * x * x) * pow(2 * y % MOD, -1, MOD) % MOD
    x3 = (lam * lam - 2 * x) % MOD
    y3 = (lam * (x - x3) - y) % MOD
    return (x3, y3)


def add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    x1, y1 = p
    x2, y2 = q
    if x1 == x2 and (y1 + y2) % MOD == 0:
        return None
    if x1 == x2 and y1 == y2:
        return dbl(p)
    lam = (y2 - y1) * pow(x2 - x1, -1, MOD) % MOD
    x3 = (lam * lam - x1 - x2) % MOD
    y3 = (lam * (x1 - x3) - y1) % MOD
    return (x3, y3)


def mul(k):
    r = None
    a = (GX, GY)
    while k:
        if k & 1:
            r = add(r, a)
        a = dbl(a)
        k >>= 1
    return r


KMAX = 8
ref = [mul(k) for k in range(1, KMAX + 1)]

dev = opencl.Device()
src = ""
for f in ("keccak.cl", "secp256k1.cl", "vanity.cl"):
    with open(os.path.join(ROOT, "gpu", f), "r", encoding="utf-8") as fh:
        src += "\n" + fh.read()
dev.build(src, ["test_point"])

N = KMAX
K = (C.c_uint * (N * 8))()
for i, k in enumerate(range(1, KMAX + 1)):
    for j in range(8):
        K[i * 8 + j] = (k >> (32 * j)) & 0xFFFFFFFF
dev.buffer("k", N * 8 * 4, opencl.CL_MEM_READ_ONLY)
dev.write("k", N * 8 * 4, K)
OUT = (C.c_ubyte * (N * 64))()
dev.buffer("out", N * 64, opencl.CL_MEM_WRITE_ONLY)
dev.run("test_point", N, 1, [("k",), ("out",)])
dev.finish()
dev.read("out", N * 64, OUT)
dev.release()

for i, k in enumerate(range(1, KMAX + 1)):
    got = bytes(OUT[i * 64:(i + 1) * 64]).hex()
    if ref[i] is None:
        exp = "-"
    else:
        exp = (hex(ref[i][0])[2:].zfill(64) + hex(ref[i][1])[2:].zfill(64))
    ok = "OK " if got == exp else "BAD"
    print(f"{ok} k={k}")
    if got != exp:
        print(f"    gpu x={got[:64]}")
        print(f"    gpu y={got[64:]}")
        print(f"    ref x={exp[:64]}")
        print(f"    ref y={exp[64:]}")

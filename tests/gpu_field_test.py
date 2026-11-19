# -*- coding: utf-8 -*-
"""GPU 有限域运算正确性验证：加 / 减 / 乘 / 逆 对比 Python 大整数"""

import ctypes as C
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))
import opencl  # noqa: E402

PP = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 256
random.seed(20261118)


def to_limbs(v):
    return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(8)]


def from_limbs(ls):
    return sum(int(x) << (32 * i) for i, x in enumerate(ls))


def run(kernel, vals_a, vals_b=None):
    dev = opencl.Device()
    with open(os.path.join(ROOT, "gpu", "secp256k1.cl"), "r", encoding="utf-8") as fh:
        src = fh.read()
    names = [kernel]
    dev.build(src, names)

    A = (C.c_uint * (N * 8))()
    for i, v in enumerate(vals_a):
        for j, l in enumerate(to_limbs(v)):
            A[i * 8 + j] = l
    dev.buffer("a", N * 8 * 4, opencl.CL_MEM_READ_ONLY, A)

    if vals_b is not None:
        B = (C.c_uint * (N * 8))()
        for i, v in enumerate(vals_b):
            for j, l in enumerate(to_limbs(v)):
                B[i * 8 + j] = l
        dev.buffer("b", N * 8 * 4, opencl.CL_MEM_READ_ONLY, B)

    Out = (C.c_uint * (N * 8))()
    dev.buffer("o", N * 8 * 4, opencl.CL_MEM_WRITE_ONLY, Out)

    args = [("a",), ("b",), ("o",)] if vals_b is not None else [("a",), ("o",)]
    dev.run(kernel, N, min(64, N), args)
    dev.finish()
    dev.read("o", N * 8 * 4, Out)
    res = [from_limbs([Out[i * 8 + j] for j in range(8)]) for i in range(N)]
    dev.release()
    return res


a = [random.getrandbits(256) % PP for _ in range(N)]
b = [random.getrandbits(256) % PP for _ in range(N)]
# 边界值
a[0], b[0] = PP - 1, PP - 1
a[1], b[1] = PP - 1, 1
a[2], b[2] = 0, PP - 1
a[3], b[3] = 1, 1

fails = 0

r = run("test_mul", a, b)
for i in range(N):
    exp = (a[i] * b[i]) % PP
    if r[i] != exp:
        fails += 1
        if fails <= 3:
            print(f"mul[{i}] gpu={hex(r[i])} exp={hex(exp)}")
print(f"mul: {N - fails}/{N}")

f2 = 0
r = run("test_add", a, b)
for i in range(N):
    if r[i] != (a[i] + b[i]) % PP:
        f2 += 1
        if f2 <= 3:
            print(f"add[{i}] gpu={hex(r[i])} exp={hex((a[i]+b[i])%PP)}")
print(f"add: {N - f2}/{N}")

f3 = 0
r = run("test_sub", a, b)
for i in range(N):
    if r[i] != (a[i] - b[i]) % PP:
        f3 += 1
        if f3 <= 3:
            print(f"sub[{i}] gpu={hex(r[i])} exp={hex((a[i]-b[i])%PP)}")
print(f"sub: {N - f3}/{N}")

f4 = 0
inv_in = [random.getrandbits(256) % PP or 1 for _ in range(N)]
r = run("test_inv", inv_in)
for i in range(N):
    if (r[i] * inv_in[i]) % PP != 1:
        f4 += 1
        if f4 <= 3:
            print(f"inv[{i}] gpu={hex(r[i])} 乘积 != 1")
print(f"inv: {N - f4}/{N}")

bad = fails + f2 + f3 + f4
print("RESULT:", "PASS" if bad == 0 else f"FAIL ({bad})")
sys.exit(0 if bad == 0 else 1)

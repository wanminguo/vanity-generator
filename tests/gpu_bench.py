# -*- coding: utf-8 -*-
"""GPU 吞吐量基准：不同 chunk / work-item 配置下测地址/秒"""

import ctypes as C
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))
import opencl  # noqa: E402

N_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
WORKERS = 2048
STEPS = 256
CHUNK = 8
random.seed(1)


def limbs(v):
    return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(8)]


dev = opencl.Device()
src = ""
for f in ("keccak.cl", "secp256k1.cl", "vanity.cl"):
    with open(os.path.join(ROOT, "gpu", f), "r", encoding="utf-8") as fh:
        src += "\n" + fh.read()

t0 = time.time()
dev.build(src, ["vanity_evm"])
print(f"编译耗时 {time.time()-t0:.2f}s")

K = (C.c_uint * (WORKERS * 8))()
for i in range(WORKERS):
    v = random.getrandbits(256) % N_ORDER
    for j, l in enumerate(limbs(v)):
        K[i * 8 + j] = l
dev.buffer("k0", WORKERS * 8 * 4, opencl.CL_MEM_READ_ONLY)
dev.write("k0", WORKERS * 8 * 4, K)
RMAX, RRULE = 8, 40
ZERO = (C.c_ubyte * (RMAX * RRULE))()
ZEROI = (C.c_int * RMAX)()
dev.buffer("rules_pre", RMAX * RRULE, opencl.CL_MEM_READ_ONLY); dev.write("rules_pre", RMAX * RRULE, ZERO)
dev.buffer("rules_suf", RMAX * RRULE, opencl.CL_MEM_READ_ONLY); dev.write("rules_suf", RMAX * RRULE, ZERO)
dev.buffer("rules_plen", RMAX * 4, opencl.CL_MEM_READ_ONLY); dev.write("rules_plen", RMAX * 4, ZEROI)
dev.buffer("rules_slen", RMAX * 4, opencl.CL_MEM_READ_ONLY); dev.write("rules_slen", RMAX * 4, ZEROI)

max_hits = 64
HC = (C.c_uint * 4)(0)
META = (C.c_uint * (max_hits * 3))()
ADDR = (C.c_ubyte * (max_hits * 20))()
dev.buffer("hc", 16, opencl.CL_MEM_READ_WRITE)
dev.buffer("meta", max_hits * 12, opencl.CL_MEM_WRITE_ONLY)
dev.buffer("addr", max_hits * 20, opencl.CL_MEM_WRITE_ONLY)

total = WORKERS * STEPS
args = [
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
]

# 预热
dev.run("vanity_evm", WORKERS, 32, args)
dev.finish()

for mode in ("local=32", "local=64", "local=0"):
    local = {"local=32": 32, "local=64": 64, "local=0": 0}[mode]
    dev.run("vanity_evm", WORKERS, local, args)
    t0 = time.time()
    dev.finish()
    dt = time.time() - t0
    print(f"{mode:10s} {total} 地址用时 {dt:.3f}s  =>  {total/dt:,.0f} addr/s")

dev.release()

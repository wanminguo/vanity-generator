# -*- coding: utf-8 -*-
"""GPU 端到端：指定前缀揽号，并验证「命中地址 <-> 私钥」完全对应"""

import ctypes as C
import json
import os
import random
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))
import opencl  # noqa: E402

N_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
NODE = r"C:\Program Files\nodejs\node.exe"
WORKERS = 1024
STEPS = 2048
CHUNK = 8
PREFIX = "abc"
hexmap = "0123456789abcdef"


def limbs(v):
    return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(8)]


random.seed(7)
k0 = [random.getrandbits(256) % (N_ORDER - STEPS - 10) + 1 for _ in range(WORKERS)]

dev = opencl.Device()
src = ""
for f in ("keccak.cl", "secp256k1.cl", "vanity.cl"):
    with open(os.path.join(ROOT, "gpu", f), "r", encoding="utf-8") as fh:
        src += "\n" + fh.read()
dev.build(src, ["vanity_evm"])

K = (C.c_uint * (WORKERS * 8))()
for i, v in enumerate(k0):
    for j, l in enumerate(limbs(v)):
        K[i * 8 + j] = l
dev.buffer("k0", WORKERS * 8 * 4, opencl.CL_MEM_READ_ONLY)
dev.write("k0", WORKERS * 8 * 4, K)

pv = [hexmap.index(c) for c in PREFIX]
RMAX, RRULE = 8, 40
PRE = (C.c_ubyte * (RMAX * RRULE))()
for i, v in enumerate(pv):
    PRE[i] = v
SUF = (C.c_ubyte * (RMAX * RRULE))()
PLEN = (C.c_int * RMAX)(len(pv), 0, 0, 0, 0, 0, 0, 0)
SLEN = (C.c_int * RMAX)(0, 0, 0, 0, 0, 0, 0, 0)
dev.buffer("rules_pre", RMAX * RRULE, opencl.CL_MEM_READ_ONLY); dev.write("rules_pre", RMAX * RRULE, PRE)
dev.buffer("rules_suf", RMAX * RRULE, opencl.CL_MEM_READ_ONLY); dev.write("rules_suf", RMAX * RRULE, SUF)
dev.buffer("rules_plen", RMAX * 4, opencl.CL_MEM_READ_ONLY); dev.write("rules_plen", RMAX * 4, PLEN)
dev.buffer("rules_slen", RMAX * 4, opencl.CL_MEM_READ_ONLY); dev.write("rules_slen", RMAX * 4, SLEN)

expect = WORKERS * STEPS // (16 ** len(PREFIX))
max_hits = max(64, expect * 3)
HC = (C.c_uint * 4)(0)
META = (C.c_uint * (max_hits * 3))()
ADDR = (C.c_ubyte * (max_hits * 20))()
dev.buffer("hc", 16, opencl.CL_MEM_READ_WRITE); dev.write("hc", 16, HC)
dev.buffer("meta", max_hits * 12, opencl.CL_MEM_WRITE_ONLY)
dev.buffer("addr", max_hits * 20, opencl.CL_MEM_WRITE_ONLY)

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

t0 = time.time()
dev.run("vanity_evm", WORKERS, 32, args)
dev.finish()
dt = time.time() - t0
dev.read("hc", 4, HC)
dev.read("meta", max_hits * 12, META)
dev.read("addr", max_hits * 20, ADDR)
dev.release()

total = WORKERS * STEPS
got = HC[0]
print(f"扫描 {total:,} 地址，用时 {dt:.3f}s => {total/dt:,.0f} addr/s")
print(f"命中 {got} 条（按 16^{len(PREFIX)} 概率预期约 {expect}）")

records = []
for i in range(min(got, max_hits)):
    wid = META[i * 3]
    off = META[i * 3 + 1]
    addr = bytes(ADDR[i * 20:(i + 1) * 20])
    records.append((wid, off, addr))

# 前缀必须匹配
bad_prefix = [r for r in records if r[2].hex()[:len(PREFIX)] != PREFIX]
print(f"前缀校验: {len(records) - len(bad_prefix)}/{len(records)} 正确")

# 私钥必须能复现同一地址
js = """
const fs = require('node:fs');
const { EthKeyDeriver } = require(%s);
const d = new EthKeyDeriver();
const privs = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const out = privs.map(h => Buffer.from(d.derive(Buffer.from(h, 'hex'))).toString('hex'));
fs.writeFileSync(process.argv[2], JSON.stringify(out));
""" % json.dumps(os.path.join(ROOT, "engine", "eth.js"))

privs = [(k0[wid] + off) % N_ORDER for wid, off, _ in records]
tmp = os.environ.get("TEMP", ".")
inp = os.path.join(tmp, "gpu_e2e_in.json")
outp = os.path.join(tmp, "gpu_e2e_out.json")
with open(inp, "w", encoding="utf-8") as fh:
    json.dump([hex(p)[2:].zfill(64) for p in privs], fh)
r = subprocess.run([NODE, "-e", js, inp, outp], capture_output=True, text=True, encoding="utf-8")
if r.returncode != 0:
    print("node:", r.stderr[:400])
    sys.exit(1)
with open(outp, "r", encoding="utf-8") as fh:
    refs = json.load(fh)

fails = 0
for i, (wid, off, addr) in enumerate(records):
    if addr.hex() != refs[i]:
        fails += 1
        if fails <= 3:
            print(f"私钥复现不一致 wid={wid} off={off} gpu={addr.hex()} ref={refs[i]}")

print(f"私钥复现: {len(records) - fails}/{len(records)} 一致")
ok = len(bad_prefix) == 0 and fails == 0 and got > 0
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

# -*- coding: utf-8 -*-
"""只验证标量乘 k*G：GPU 输出的公钥坐标必须等于 Node 的公钥"""

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
N = 16
random.seed(20261118)
ks = [random.getrandbits(256) % (N_ORDER - 1000) + 1 for _ in range(N)]
ks[0] = 1
ks[1] = N_ORDER - 1


def limbs(v):
    return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(8)]


dev = opencl.Device()
src = ""
for f in ("keccak.cl", "secp256k1.cl", "vanity.cl"):
    with open(os.path.join(ROOT, "gpu", f), "r", encoding="utf-8") as fh:
        src += "\n" + fh.read()
dev.build(src, ["test_point"])

K = (C.c_uint * (N * 8))()
for i, v in enumerate(ks):
    for j, l in enumerate(limbs(v)):
        K[i * 8 + j] = l
dev.buffer("k", N * 8 * 4, opencl.CL_MEM_READ_ONLY)
dev.write("k", N * 8 * 4, K)
OUT = (C.c_ubyte * (N * 64))()
dev.buffer("out", N * 64, opencl.CL_MEM_WRITE_ONLY)
dev.run("test_point", N, 1, [("k",), ("out",)])
dev.finish()
dev.read("out", N * 64, OUT)
dev.release()

gpu = [bytes(OUT[i * 64:(i + 1) * 64]).hex() for i in range(N)]

js = """
const fs = require('node:fs');
const crypto = require('node:crypto');
const ks = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const ecdh = crypto.createECDH('secp256k1');
const out = ks.map(h => {
  ecdh.setPrivateKey(Buffer.from(h, 'hex'));
  return Buffer.from(ecdh.getPublicKey(null, 'uncompressed')).subarray(1).toString('hex');
});
fs.writeFileSync(process.argv[2], JSON.stringify(out));
"""
tmp = os.environ.get("TEMP", ".")
inp = os.path.join(tmp, "gpu_point_in.json")
outp = os.path.join(tmp, "gpu_point_out.json")
with open(inp, "w", encoding="utf-8") as fh:
    json.dump([hex(k)[2:].zfill(64) for k in ks], fh)
r = subprocess.run([NODE, "-e", js, inp, outp], capture_output=True, text=True, encoding="utf-8")
if r.returncode != 0:
    print("node:", r.stderr[:400])
    sys.exit(1)
with open(outp, "r", encoding="utf-8") as fh:
    ref = json.load(fh)

fails = 0
for i in range(N):
    if gpu[i] != ref[i]:
        fails += 1
        if fails <= 4:
            print(f"#{i} k={hex(ks[i])[:20]}\n   gpu={gpu[i][:40]}...\n   ref={ref[i][:40]}...")
print(f"标量乘: {N - fails}/{N} 一致")
sys.exit(0 if fails == 0 else 1)

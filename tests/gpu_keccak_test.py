# -*- coding: utf-8 -*-
"""GPU Keccak-256 与 Node 参考实现对比"""

import ctypes as C
import json
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gpu"))
import opencl  # noqa: E402

NODE = None
for p in (r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"):
    if os.path.isfile(p):
        NODE = p
        break

N = 512
random.seed(20261118)

inputs = [bytes(random.getrandbits(8) for _ in range(64)) for _ in range(N)]
# 掺入几个边界值
inputs[0] = bytes(64)
inputs[1] = bytes([0xFF]) * 64
inputs[2] = bytes(range(64))

dev = opencl.Device()
with open(os.path.join(ROOT, "gpu", "keccak.cl"), "r", encoding="utf-8") as fh:
    src = fh.read()
dev.build(src, ["keccak64"])

in_buf = (C.c_ubyte * (N * 64))()
for i, b in enumerate(inputs):
    for j in range(64):
        in_buf[i * 64 + j] = b[j]
dev.buffer("in", N * 64, opencl.CL_MEM_READ_ONLY, in_buf)
out_buf = (C.c_ubyte * (N * 32))()
dev.buffer("out", N * 32, opencl.CL_MEM_WRITE_ONLY)

dev.run("keccak64", N, min(128, N), [("in",), ("out",)])
dev.finish()
dev.read("out", N * 32, out_buf)

gpu_hashes = [bytes(out_buf[i * 32:(i + 1) * 32]) for i in range(N)]

# Node 侧算参考值（输入写临时文件，避免命令行过长）
js = """
const fs = require('node:fs');
const { keccak256 } = require(%s);
const inputs = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const out = inputs.map(h => {
  const bytes = keccak256(Buffer.from(h, 'hex'));
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
});
fs.writeFileSync(process.argv[2], JSON.stringify(out));
""" % json.dumps(os.path.join(ROOT, "engine", "keccak.js"))

tmp_dir = os.path.join(os.environ.get("TEMP", "."))
in_path = os.path.join(tmp_dir, "gpu_keccak_in.json")
out_path = os.path.join(tmp_dir, "gpu_keccak_out.json")
with open(in_path, "w", encoding="utf-8") as fh:
    json.dump([b.hex() for b in inputs], fh)

res = subprocess.run([NODE, "-e", js, in_path, out_path],
                     capture_output=True, text=True, encoding="utf-8")
if res.returncode != 0:
    print("node 失败:", res.stderr[:400])
    sys.exit(1)
with open(out_path, "r", encoding="utf-8") as fh:
    ref = [bytes.fromhex(h) for h in json.load(fh)]

fails = 0
for i in range(N):
    if gpu_hashes[i] != ref[i]:
        fails += 1
        if fails <= 3:
            print(f"不一致 #{i}: gpu={gpu_hashes[i].hex()} ref={ref[i].hex()}")

print(f"keccak: {N - fails}/{N} 一致")
dev.release()
sys.exit(1 if fails else 0)

# -*- coding: utf-8 -*-
"""GPU 引擎级验证：Base58 三条链 + EVM 回归

从 found 事件拿到的私钥重新派生地址，验证「地址 ↔ 私钥」自洽。

运行：C:\\Python314\\python.exe tests\\gpu_b58_engine.py
"""

import hashlib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from gpu_engine import GpuRunner  # noqa: E402
from keccak_py import keccak256, to_checksum  # noqa: E402

ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
P = 2 ** 256 - 2 ** 32 - 977
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

VERS = {"btc": 0x00, "doge": 0x1E, "trx": 0x41}


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


def addr_of(priv, chain):
    x, y = mul(priv)
    xb, yb = x.to_bytes(32, "big"), y.to_bytes(32, "big")
    if chain in ("btc", "doge"):
        cp = bytes([2 | (y & 1)]) + xb
        h20 = hashlib.new("ripemd160", hashlib.sha256(cp).digest()).digest()
    elif chain == "trx":
        h20 = keccak256(xb + yb)[12:]
    else:
        return to_checksum(keccak256(xb + yb)[12:].hex())
    payload = bytes([VERS[chain]]) + h20
    return b58encode(payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4])


def run_case(chain, prefix, suffix, count=2):
    events = []
    runner = GpuRunner(events.append)
    runner.start(chain, prefix, suffix, 0, count)
    t0 = time.time()
    while runner.running and time.time() - t0 < 60:
        time.sleep(0.1)
    if runner.running:
        runner.stop()
        time.sleep(0.3)

    found = [e for e in events if e.get("t") == "found"]
    err = [e for e in events if e.get("t") == "error"]
    kinds = {}
    for e in events:
        kinds[e.get("t")] = kinds.get(e.get("t"), 0) + 1
    print(f"    事件 {kinds}")
    if err:
        print(f"{chain:5} 前缀={prefix!r} → 错误 {err[0]['message']}")
        return False, 0.0

    t = [e for e in events if e.get("t") in ("done", "progress")]
    elapsed = t[-1]["elapsed"] if t else 0
    ok = 0
    for e in found:
        priv = int(e["privHex"], 16)
        want = addr_of(priv, chain)
        if e["address"] == want:
            ok += 1
        else:
            print(f"  {chain} 私钥 {e['privHex'][:12]}… want={want} got={e['address']}")
    hit_prefix = all(e["address"].startswith(prefix) for e in found)
    print(f"{chain:5} 前缀={prefix!r} 后缀={suffix!r} → 命中 {len(found)}/{count}，"
          f"地址自洽 {ok}/{len(found)}，前缀符合 {hit_prefix}")
    return (len(found) == count and ok == len(found) and hit_prefix), elapsed


print("=" * 62)
total = 0
bad = 0
for chain, pre, suf in [("btc", "1", ""), ("btc", "", "z"), ("doge", "D", ""),
                        ("trx", "T", ""), ("trx", "", "8")]:
    ok, _ = run_case(chain, pre, suf, 2)
    total += 1
    bad += 0 if ok else 1

print("=" * 62)
print("RESULT:", "PASS" if bad == 0 else f"FAIL ({bad}/{total})")
sys.exit(0 if bad == 0 else 1)

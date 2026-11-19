# -*- coding: utf-8 -*-
"""界面层：Base58 链（BTC / TRX）在 GPU 模式下的端到端冒烟

切换链 → 开 GPU → 生成 → 用私钥重算地址，校验界面显示的正确性。
"""

import hashlib
import os
import sys
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import main as m                      # noqa: E402
from keccak_py import keccak256       # noqa: E402

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


def padd(p, q):
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


def pmul(k):
    r = None
    b = (GX, GY)
    while k:
        if k & 1:
            r = padd(r, b)
        b = padd(b, b)
        k >>= 1
    return r


def addr_of(priv, chain):
    x, y = pmul(priv)
    xb, yb = x.to_bytes(32, "big"), y.to_bytes(32, "big")
    if chain in ("btc", "doge"):
        h20 = hashlib.new("ripemd160", hashlib.sha256(bytes([2 | (y & 1)]) + xb).digest()).digest()
    else:
        h20 = keccak256(xb + yb)[12:]
    payload = bytes([VERS[chain]]) + h20
    chk = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return b58encode(payload + chk)


ok, fail = [], []


def check(name, cond, extra=""):
    (ok if cond else fail).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))


root = tk.Tk()
root.withdraw()
app = m.HUDApp(root)

check("默认走 CPU", app.use_gpu is False)
app._toggle_gpu()
check("已切到 GPU", app.use_gpu is True and app.gpu_info is not None)

for chain, prefix in (("btc", "1"), ("trx", "T")):
    app.chain = chain
    app._rebuild()
    app.entries["prefix"]._var.set(prefix)
    app.entries["suffix"]._var.set("")
    app.entries["count"]._var.set("2")
    app._on_start()
    check(f"{chain} 已进入运行态", app.running is True)

    t0 = time.time()
    while app.running and time.time() - t0 < 30:
        root.update()
        time.sleep(0.02)
    root.update()
    check(f"{chain} 生成已结束", app.running is False, f"{time.time()-t0:.1f}s")
    check(f"{chain} 拿到结果", len(app.results) == 2, str(len(app.results)))

    for r in app.results:
        want = addr_of(int(r["priv"], 16), chain)
        check(f"{chain} 地址与私钥自洽", r["address"] == want, f"{r['address']} vs {want}")
        check(f"{chain} 前缀符合", r["address"].startswith(prefix), r["address"])

app.root.destroy()
print(f"\n{len(ok)} PASS / {len(fail)} FAIL")
sys.exit(0 if not fail else 1)

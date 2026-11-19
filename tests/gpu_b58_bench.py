# -*- coding: utf-8 -*-
"""Base58 链 GPU 吞吐实测（BTC / DOGE / TRX）

用固定长度的前缀做真实搜索，取 progress 事件的 rate 作为稳态吞吐。

运行：C:\\Python314\\python.exe tests\\gpu_b58_bench.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from gpu_engine import GpuRunner  # noqa: E402


def bench(chain, prefix, count=1, limit=90):
    ev = []
    r = GpuRunner(ev.append)
    r.start(chain, prefix, "", 0, count)
    t0 = time.time()
    while r.running and time.time() - t0 < limit:
        time.sleep(0.05)
    if r.running:
        r.stop()
        time.sleep(0.3)

    rates = [e["rate"] for e in ev if e.get("t") == "progress" and e.get("rate")]
    done = [e for e in ev if e.get("t") == "done"]
    found = len([e for e in ev if e.get("t") == "found"])
    el = done[0]["elapsed"] if done else (time.time() - t0)
    att = done[0]["attempts"] if done else 0
    peak = max(rates) if rates else 0
    avg = att / el if el > 0 else 0
    print(f"{chain:5} 前缀={prefix!r:10} 命中={found} 用时={el:6.2f}s "
          f"次数={att:>12,} 平均={int(avg):>11,}/s 峰值={peak:>11,}/s")
    return avg


print("=" * 78)
res = {}
res["btc"] = bench("btc", "1abcde")
res["doge"] = bench("doge", "Dabcde")
res["trx"] = bench("trx", "Tabcde")
print("=" * 78)
for k, v in res.items():
    print(f"{k.upper():5} ≈ {v/1e6:.1f} 百万地址/秒")

# -*- coding: utf-8 -*-
"""界面层 GPU 开关冒烟测试：按钮存在、可切换、GPU 生成能出结果"""

import os
import sys
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import main as m  # noqa: E402

ok, fail = [], []


def check(name, cond, extra=""):
    (ok if cond else fail).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))


root = tk.Tk()
root.withdraw()
app = m.HUDApp(root)

check("GPU 探测结果存在", app.gpu_info is not None, str(app.gpu_info))
check("gpu 按钮已创建", hasattr(app, "btn_gpu"))
check("默认走 CPU", app.use_gpu is False)
check("按钮默认文案为 CPU", "CPU" in app.btn_gpu["label"], app.btn_gpu["label"])

app._toggle_gpu()
check("切换后为 GPU", app.use_gpu is True)
check("按钮文案切换", "GPU" in app.btn_gpu["label"], app.btn_gpu["label"])

# 跑一次免费前缀（3 位）的 GPU 生成
app.entries["prefix"]._var.set("abc")
app.entries["suffix"]._var.set("")
app.entries["count"]._var.set("2")
app._on_start()
check("已进入运行态", app.running is True)

t0 = time.time()
while app.running and time.time() - t0 < 20:
    root.update()
    time.sleep(0.02)

root.update()
check("生成已结束", app.running is False, f"{time.time()-t0:.1f}s")
check("拿到结果", len(app.results) >= 1, str(len(app.results)))

if app.results:
    r = app.results[0]
    check("地址前缀匹配", r["address"].lower().replace("0x", "").startswith("abc"), r["address"])
    check("私钥 64 位", len(r["priv"]) == 64)
    check("地址为校验和格式", r["address"][2:3].isupper() or r["address"][2:3].islower())

app.root.destroy()
print(f"\n{len(ok)} PASS / {len(fail)} FAIL")
sys.exit(0 if not fail else 1)

# -*- coding: utf-8 -*-
"""界面布局测试：面板 04（授权结果）与面板 02 控制行重排"""

import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import main as m   # noqa: E402

ok, fail = [], []


def check(name, cond, extra=""):
    (ok if cond else fail).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))


def center(btn):
    x1, y1, x2, y2 = btn["rect"]
    return (x1 + x2) / 2, (y1 + y2) / 2


root = tk.Tk()
root.withdraw()
app = m.HUDApp(root)
c = app.canvas

check("窗口高度扩展到 4 面板", m.DESIGN_H == 872, str(m.DESIGN_H))

# 面板 02：控制行同排
row = {k: getattr(app, k)["rect"] for k in ("btn_gpu", "btn_start", "btn_stop")}
check("GPU 按钮在控制行", row["btn_gpu"][1] == 312, str(row["btn_gpu"]))
check("开始按钮在 GPU 右侧", row["btn_start"][0] > row["btn_gpu"][2], str(row["btn_start"]))
check("中止按钮在开始右侧", row["btn_stop"][0] > row["btn_start"][2], str(row["btn_stop"]))
check("控制行三键同高", row["btn_gpu"][1] == row["btn_start"][1] == row["btn_stop"][1])
check("控制行不超出面板", row["btn_stop"][2] < 932)

# 命中测试：点按钮中心应命中对应按钮
for key in ("btn_gpu", "btn_start", "btn_stop", "btn_license", "btn_copy_id"):
    btn = getattr(app, key)
    cx, cy = center(btn)
    hit = app._hit_button(m.S(cx), m.S(cy))
    check(f"命中测试 {key}", hit is btn, f"点({cx:.0f},{cy:.0f}) → {hit['label'] if hit else None}")

# 面板 04：设备 ID 与授权状态位置
bbox_mid = c.bbox(app.dyn["mid"])
check("设备 ID 落在面板 04 内", 696 < bbox_mid[1] < 812, str(bbox_mid))
check("设备 ID 为黄色", c.itemcget(app.dyn["mid"], "fill") == m.AMBER,
      c.itemcget(app.dyn["mid"], "fill"))
check("设备 ID 已填充", "VG-" in c.itemcget(app.dyn["mid"], "text"),
      c.itemcget(app.dyn["mid"], "text"))
bbox_credit = c.bbox(app.dyn["credit"])
check("授权状态落在面板 04 内", 696 < bbox_credit[1] < 812, str(bbox_credit))
check("授权状态有文字", c.itemcget(app.dyn["credit"], "text") != "",
      c.itemcget(app.dyn["credit"], "text"))
check("授权码按钮在面板 04", app.btn_license["rect"][1] >= 696, str(app.btn_license["rect"]))
check("复制 ID 按钮在面板 04", app.btn_copy_id["rect"][1] >= 696, str(app.btn_copy_id["rect"]))
check("设备 ID 与复制按钮不重叠", app.btn_copy_id["rect"][0] > bbox_mid[2],
      f"{bbox_mid[2]} vs {app.btn_copy_id['rect'][0]}")

# 面板 03：结果区不与标签重叠
check("地址文字在地址标签下方", c.bbox(app.dyn["addr"])[1] > 506 + 12)
check("私钥文字在私钥标签下方", c.bbox(app.dyn["key"])[1] > 566 + 12)

# 运行状态文本回到面板 02 右侧
bbox_status = c.bbox(app.dyn["status"])
check("状态文字在面板 02", 264 < bbox_status[1] < 458, str(bbox_status))
check("状态文字在控制行高度", 300 < bbox_status[1] < 350, str(bbox_status))

# 切到英文：整块重绘不报错，面板 04 仍在
app.lang = "en"
app._rebuild()
check("英文重绘后仍有面板 04 按钮", app.btn_license["rect"][1] >= 696)
check("英文设备 ID 标签存在", app.t("device_id") == "DEVICE ID")
app.lang = "zh"
app._rebuild()

# 真跑一轮（CPU），确认坐标调整没影响生成流程
app.entries["prefix"]._var.set("8888")
app.entries["count"]._var.set("1")
app._on_start()
check("已进入运行态", app.running is True)
import time                                          # noqa: E402
t0 = time.time()
while app.running and time.time() - t0 < 60:
    root.update()
    time.sleep(0.02)
root.update()
check("生成已结束", app.running is False, f"{time.time()-t0:.1f}s")
check("拿到结果", len(app.results) == 1, str(len(app.results)))
if app.results:
    r = app.results[0]
    check("前缀匹配", r["address"].lower().startswith("0x8888"), r["address"])
    check("私钥 64 位", len(r["priv"]) == 64)

root.destroy()
print(f"\n{len(ok)} PASS / {len(fail)} FAIL")
sys.exit(0 if not fail else 1)

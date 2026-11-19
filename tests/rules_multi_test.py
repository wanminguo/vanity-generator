#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多规则并行匹配测试：引擎侧（真跑 node）+ 界面侧（不启动真引擎）。

运行：C:\\Python314\\python.exe tests\\rules_multi_test.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
ROOT_DIR = os.path.abspath(os.path.join(APP_DIR, ".."))
sys.path.insert(0, APP_DIR)

import license as lic  # noqa: E402
import main as appmod  # noqa: E402

TMP = tempfile.mkdtemp(prefix="vanity_rules_")
_RealLedger = lic.Ledger


def _test_ledger(*args, **kwargs):
    return _RealLedger(os.path.join(TMP, "ledger.json"))


lic.Ledger = _test_ledger

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail != "" else ""))
    if not cond:
        FAIL += 1


def node_bin():
    for p in (r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"):
        if os.path.isfile(p):
            return p
    return shutil.which("node")


NODE = node_bin()
ENGINE = os.path.join(ROOT_DIR, "engine", "vanity.js")


def run_engine(rules, count=1, threads=6, timeout=90):
    cmd = [NODE, ENGINE, "--rules", json.dumps(rules), "--count", str(count),
           "--threads", str(threads), "--interval", "300"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         timeout=timeout, cwd=ROOT_DIR)
    events = []
    for ln in out.stdout.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return events, out


class StubRunner:
    def __init__(self, on_event):
        self.on_event = on_event
        self.started = None

    def start(self, chain, prefix, suffix, threads, count, rules=None):
        self.started = {"chain": chain, "prefix": prefix, "suffix": suffix,
                        "threads": threads, "count": count, "rules": rules}

    def stop(self):
        pass


class FakeBox:
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.infos = []

    def showwarning(self, *a, **k):
        self.warnings.append(a)

    def showerror(self, *a, **k):
        self.errors.append(a)

    def showinfo(self, *a, **k):
        self.infos.append(a)


class FakeLicenseDialog:
    def __init__(self, master, t, ledger):
        self.result = None          # 用户直接取消，不导入任何码


appmod.EngineRunner = StubRunner
BOX = FakeBox()
appmod.messagebox = BOX
appmod.LicenseDialog = FakeLicenseDialog

print("[1] 引擎：三条规则并行，命中任意一条")
events, proc = run_engine([{"prefix": "8888"}, {"prefix": "7777"}, {"suffix": "6666"}],
                          count=3, threads=10)
ready = [e for e in events if e.get("t") == "ready"]
founds = [e for e in events if e.get("t") == "found"]
check("引擎正常结束", proc.returncode == 0, proc.returncode)
check("ready 上报 3 条规则", bool(ready) and ready[0].get("ruleCount") == 3,
      ready[0].get("ruleCount") if ready else "no-ready")
if ready:
    tgt = ready[0].get("target")
    # 三条各 16^4，概率相加 → 期望 65536/3
    check("合并期望次数正确", abs(tgt - 65536 / 3) < 1, tgt)
    check("最长固定位 4 位", ready[0].get("fixedChars") == 4, ready[0].get("fixedChars"))

check("收满 3 条", len(founds) == 3, len(founds))
EXPECT = [
    (0, lambda a: a.startswith("8888")),
    (1, lambda a: a.startswith("7777")),
    (2, lambda a: a.endswith("6666")),
]
for i, ev in enumerate(founds):
    key = ev.get("matchKey") or ""
    idx = ev.get("ruleIndex")
    check(f"第 {i + 1} 条带合法 ruleIndex", idx in (0, 1, 2), idx)
    ok = EXPECT[idx][1](key) if isinstance(idx, int) and 0 <= idx < 3 else False
    check(f"第 {i + 1} 条符合它标称的规则", ok, key)

print("[2] 引擎：只填后缀 / 两条同长规则")
events2, proc2 = run_engine([{"suffix": "abcd"}, {"prefix": "dead"}], count=2, threads=10)
ready2 = [e for e in events2 if e.get("t") == "ready"]
founds2 = [e for e in events2 if e.get("t") == "found"]
check("两条规则 ready", bool(ready2) and ready2[0].get("ruleCount") == 2)
check("收满 2 条", len(founds2) == 2, len(founds2))
if ready2:
    check("两条同长规则期望减半", abs(ready2[0]["target"] - 65536 / 2) < 1, ready2[0]["target"])

print("[3] 引擎：非法字符定位到具体规则")
events3, proc3 = run_engine([{"prefix": "888"}, {"prefix": "zzz"}], count=1)
errs = [e for e in events3 if e.get("t") == "error"]
check("报错退出", proc3.returncode != 0 and bool(errs), proc3.returncode)
check("指明第 2 条规则", bool(errs) and "第 2 条规则" in errs[0].get("message", ""),
      errs[0].get("message") if errs else "")

import tkinter as tk  # noqa: E402

root = tk.Tk()
root.withdraw()
app = appmod.HUDApp(root)
app.use_gpu = False
app.active = app.runner
root.update()

ORIG = appmod.SCALE
appmod.SCALE = 1.0


def set_entry(key, value):
    app.entries[key]._var.set(value)
    app.entries[key]._placeholder = ""


print("[4] 界面：规则集合与按钮文案")
app._apply_rules([{"prefix": "8888888"}, {"prefix": "7777777"}, {"suffix": "6666"}])
check("规则计数 3", app._rule_total() == 3, app._rule_total())
check("按钮文案跟着变", "3" in app.btn_rules["label"], app.btn_rules["label"])
eff = app._effective_rules()
check("生效规则 3 条", len(eff) == 3, len(eff))
check("第一条来自主面板", eff[0]["prefix"] == "8888888", eff[0])
app._refresh_hint()
hint = app.canvas.itemcget(app.dyn["hint"], "text")
check("提示里标明并行", "3 条规则并行" in hint, hint)
check("提示最长位数 7", "固定 7 位" in hint, hint)

print("[5] 界面：空白规则被过滤")
app._apply_rules([{"prefix": ""}, {"prefix": "888"}, {"prefix": "", "suffix": ""}])
eff2 = app._effective_rules()
check("空白规则不参与", len(eff2) == 1, eff2)
check("主面板那条被清掉后只剩 1 条", app._rule_total() == 3, app._rule_total())
app._refresh_hint()
hint2 = app.canvas.itemcget(app.dyn["hint"], "text")
check("单条时不显示并行", "条规则并行" not in hint2, hint2)

print("[6] 界面：扣费取最长规则")
app._apply_rules([{"prefix": ""}, {"prefix": "88888888"}])
app.reserved = 0
app.running = False
app.runner.started = None
BOX.warnings.clear()
app._on_start()
check("8 位规则无额度被拦", app.runner.started is None)
check("取消输入码时静默返回", len(BOX.warnings) == 0, BOX.warnings[:1])

print("[6b] 界面：额度不足时给出提示")
app.license.reserve(0)
app.reserved = 0
app.running = False
app.runner.started = None
BOX.warnings.clear()
app._ask_license = lambda: True          # 假装导入过码，但次数仍不够
app._on_start()
check("仍被拦下", app.runner.started is None)
check("提示里写明固定 8 位", bool(BOX.warnings) and "8" in BOX.warnings[0][1],
      BOX.warnings[0][1] if BOX.warnings else "")

print("[7] 界面：多规则也走 GPU（不再强制切回 CPU）")
app._apply_rules([{"prefix": "8888"}, {"prefix": "7777"}])
app.gpu_runner = StubRunner(app.events.put)
app.use_gpu = True          # 假装用户开着 GPU
app.gpu_info = app.gpu_info or {"name": "stub"}
app.running = False
app.runner.started = None
app.gpu_runner.started = None
app._on_start()
check("GPU 保持开启", app.use_gpu is True, app.use_gpu)
check("走的是 GPU 引擎", app.active is app.gpu_runner, type(app.active).__name__)
check("GPU 收到 2 条规则",
      bool(app.gpu_runner.started) and len(app.gpu_runner.started["rules"]) == 2,
      app.gpu_runner.started["rules"] if app.gpu_runner.started else None)
check("GPU 也拿到首条规则的主面板字段",
      bool(app.gpu_runner.started) and app.gpu_runner.started["prefix"] == "8888",
      app.gpu_runner.started["prefix"] if app.gpu_runner.started else None)
app._on_stop()
app.use_gpu = False
app.active = app.runner

print("[8] 界面：单规则不传多规则参数")
app._apply_rules([{"prefix": "8888"}])
app.running = False
app.runner.started = None
app._on_start()
check("单规则 rules 为 None", bool(app.runner.started) and app.runner.started["rules"] is None,
      app.runner.started["rules"] if app.runner.started else None)
app._on_stop()

print("[9] 界面：结果标注命中的规则")
app._apply_rules([{"prefix": "8888"}, {"prefix": "7777"}])
app.rules_snapshot = list(app._effective_rules())
check("命中第 2 条显示 7777*", app._rule_text(1) == "7777*", app._rule_text(1))
check("越界下标不崩", app._rule_text(9) in ("7777*", "8888*", "随机"), app._rule_text(9))

appmod.SCALE = ORIG
root.destroy()
print()
print("结果：" + ("全部通过" if FAIL == 0 else f"{FAIL} 项失败"))
sys.exit(1 if FAIL else 0)

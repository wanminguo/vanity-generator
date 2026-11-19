#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
靓号生成器 —— 科幻风 HUD 桌面界面（Python tkinter，仅用标准库）

· 计算全部由本地 Node 引擎完成（engine/vanity.js），本进程只负责界面与进程管理
· 不引入任何网络模块，全程离线可用
· 支持 8 条链（5 条 EVM + BTC / DOGE / TRON）、中英双语、批量生成、Excel 导出
· 私钥默认只在内存中流转；只有用户主动点「导出 Excel」时才写入文件

界面为纯 Canvas 自绘，不使用 ttk 主题，以保证视觉统一。
"""

import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
ENGINE_JS = os.path.join(ROOT_DIR, "engine", "vanity.js")

sys.path.insert(0, APP_DIR)
import license as lic  # noqa: E402
from device_id import device_id  # noqa: E402
from xlsx_writer import default_filename, write_xlsx  # noqa: E402
import gpu_engine  # noqa: E402
import state_store  # noqa: E402  本地状态：规则/链/语言/线程/数量/GPU 记忆
import qr_code  # noqa: E402  纯标准库二维码，给购买弹窗用

# 购买授权码的页面（浏览器打开，软件自身不联网）
BUY_URL_BASE = "https://buy.wanminguo.top/vanity/"

DESIGN_W, DESIGN_H = 980, 872
CREATE_NO_WINDOW = 0x08000000

# 面板 02 里进度条与统计行的纵向位置（多处复用，集中定义防漂移）
BAR_Y1, BAR_Y2 = 372, 382
STAT_Y = 420

SCALE = 1.0


def S(v):
    """设计坐标 → 实际像素"""
    return v * SCALE


# ---------------------------------------------------------------- 视觉主题

BG = "#04070D"
GRID = "#0A1420"
GRID_BRIGHT = "#0D1B29"
PANEL_FILL = "#060C15"
ENTRY_BG = "#050B14"

CYAN = "#22E0FF"
CYAN_DIM = "#0E7C96"
CYAN_FAINT = "#0A3D4C"
GREEN = "#3BFF9E"
AMBER = "#FFB020"
RED = "#FF4D5E"
TEXT = "#CDE7F2"
MUTED = "#54718A"
DIM = "#2E4456"

F_TITLE = ("Microsoft YaHei UI", 21, "bold")
F_SUB = ("Consolas", 9)
F_LABEL = ("Consolas", 8)
F_CN = ("Microsoft YaHei UI", 9)
F_CN_SMALL = ("Microsoft YaHei UI", 8)
F_NUM = ("Consolas", 17, "bold")
F_ADDR = ("Consolas", 18)
F_KEY = ("Consolas", 12)
F_BTN = ("Microsoft YaHei UI", 10, "bold")
F_BTN_SM = ("Microsoft YaHei UI", 8)
F_DD = ("Consolas", 9)


# ---------------------------------------------------------------- 链定义

CHAINS = {
    "eth": {"tag": "ETH", "name": "Ethereum", "kind": "evm"},
    "bsc": {"tag": "BSC", "name": "BNB Chain", "kind": "evm"},
    "polygon": {"tag": "POLYGON", "name": "Polygon", "kind": "evm"},
    "arbitrum": {"tag": "ARB", "name": "Arbitrum One", "kind": "evm"},
    "base": {"tag": "BASE", "name": "Base", "kind": "evm"},
    "btc": {"tag": "BTC", "name": "Bitcoin", "kind": "base58"},
    "doge": {"tag": "DOGE", "name": "Dogecoin", "kind": "base58"},
    "trx": {"tag": "TRX", "name": "TRON", "kind": "base58"},
}
CHAIN_ORDER = ["eth", "bsc", "polygon", "arbitrum", "base", "btc", "doge", "trx"]
HEX_ALPHABET = "0123456789abcdef"
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def chain_meta(chain_id):
    c = CHAINS.get(chain_id, CHAINS["eth"])
    is_evm = c["kind"] == "evm"
    return {
        "tag": c["tag"],
        "name": c["name"],
        "is_evm": is_evm,
        "alphabet": HEX_ALPHABET if is_evm else B58_ALPHABET,
        "maxlen": 40 if is_evm else 34,
        "base": 16 if is_evm else 58,
    }


# ---------------------------------------------------------------- 文案

I18N = {
    "zh": {
        "title": "靓号生成器",
        "subtitle": "VANITY ADDRESS GENERATOR  //  MULTI-CHAIN  ·  OFFLINE",
        "no_network": "无网络能力",
        "p1": "匹配规则", "p1_sub": "MATCH RULE",
        "prefix": "前缀", "suffix": "后缀",
        "rules_btn": "规则 {n} 条",
        "rules_btn_lock": "规则 {n} 条 · 需授权",
        "rules_need_license": "多规则并行需要授权码：未授权只能匹配 1 条规则",
        "rules_title": "多规则并行匹配",
        "rules_note": "每条规则 = 前缀 + 后缀，可以只填一边；命中任意一条就产出一条结果。全部留空表示随机生成。",
        "rules_add": "+ 添加一条",
        "rules_add_locked": "+ 添加一条 · 需授权",
        "rules_apply": "确定",
        "rules_first": "主面板",
        "rules_col_no": "序号",
        "rules_active": "  ·  {n} 条规则并行",
        "p2": "运算核心", "p2_sub": "PROCESSOR",
        "count": "数量", "threads": "线程",
        "gpu_toggle_on": "GPU · {name}",
        "gpu_toggle_off": "CPU 多线程",
        "gpu_na": "未检测到 GPU",
        "gpu_bad_char": "该字符不在本链字母表中，无法用 GPU 匹配",
        "status_gpu": "GPU · {name}",
        "status_building": "正在编译 GPU 内核（首次约 2-4 分钟）…",
        "start": "开始生成", "stop": "中止",
        "p3": "输出结果", "p3_sub": "OUTPUT",
        "p4": "授权结果", "p4_sub": "LICENSE & DEVICE",
        "device_id": "设备 ID", "license_status": "授权状态",
        "copy_id": "复制 ID",
        "p4_note": "授权码可绑定本机设备 ID：把上面的 ID 发给发卡方，生成的码只能在本机使用。",
        "address": "地址", "private_key": "私钥",
        "copy_addr": "复制地址", "show": "显示", "hide": "隐藏",
        "copy_key": "复制私钥", "export": "导出 Excel",
        "attempts": "已尝试", "rate": "速度 / 秒", "elapsed": "用时", "eta": "预计剩余",
        "status_idle": "STANDBY", "status_init": "INITIALIZING",
        "status_run": "{n} THREADS ACTIVE",
        "status_hit": "TARGET ACQUIRED", "status_abort": "ABORTED",
        "status_error": "ERROR", "status_copy": "COPIED",
        "status_key_copy": "KEY COPIED", "status_export": "EXPORTED",
        "collected": "已收集 {a} / {b}",
        "credit": "额度 {n} 次",
        "credit_free": "免费区间",
        "credit_lock": "需授权码",
        "credit_tampered": "额度异常",
        "credit_clock": "系统时间异常",
        "credit_time": "有效期至 {date}",
        "credit_both": "至 {date} · 余 {n} 次",
        "mid_copied": "设备 ID 已复制",
        "buy_btn": "购买授权码",
        "buy_title": "购买授权码",
        "buy_note": "在浏览器里打开下面的地址，选套餐（设备 ID 已自动带上），付款后授权码会发到你的邮箱。\n软件本身不联网，也不会上传任何东西。",
        "buy_copy": "复制链接",
        "buy_open": "用浏览器打开",
        "buy_scan": "手机扫码购买",
        "buy_copied": "链接已复制到剪贴板",
        "buy_hint": "扫码或另存链接到手机也可以直接购买",
        "start_confirm_title": "确认开始生成",
        "cf_rules": "匹配规则",
        "cf_mode": "运算模式",
        "cf_chain": "目标链",
        "cf_qty": "生成数量",
        "cf_credit": "额度",
        "cf_rule_item": "规则 {i}  前 {pre}  后 {suf}",
        "cf_rule_more": "…共 {n} 条规则，全部参与匹配",
        "cf_rule_none": "未指定规则：直接生成随机地址",
        "cf_mode_cpu": "CPU 多线程 · {n} 线程",
        "cf_mode_gpu": "GPU · {gpu} · {n} 线程",
        "cf_credit_free": "免费区间 · 不扣额度",
        "cf_credit_use": "本次扣 {n} 次 · 剩余 {have} → {left}",
        "cf_credit_short": "需要 {n} 次，当前只有 {have} 次",
        "cf_warn": "点「确认开始」立即扣额度，中止或没找够都不退。",
        "cf_warn_short": "额度不足：确认后会先要求输入授权码，够扣才开跑。",
        "cf_warn_free": "固定位数在免费区间内，本次不扣额度。",
        "cf_ok": "确认开始",
        "cf_cancel": "取消",
        "license_btn": "授权码",
        "license_title": "输入授权码",
        "license_prompt": "粘贴授权码（形如 xxxxx.yyyyy）",
        "license_submit": "导入",
        "license_cancel": "取消",
        "license_empty": "请先粘贴授权码",
        "license_ok_short": "已导入 +{n} 次",
        "need_credit": "该规则固定 {fixed} 位，已超过免费上限 {free} 位。\n需要 {need} 次额度，当前只有 {have} 次。",
        "credit_hint": "  ·  超过 {free} 位需授权码（每条扣 1 次）",
        "credit_charged": "已扣 {n} 次额度（点开始即扣，中止或没找够都不退）",
        "hint_empty": "未指定规则 · 将直接生成随机地址（不消耗难度）",
        "hint_bad": "含非法字符：{chars}",
        "hint_diff": "固定 {n} 位 · 平均约 {target} 次 · 当前速度下约 {eta}",
        "hint_slow": "  ·  建议降低位数",
        "hint_case": "  ·  该链地址区分大小写",
        "hint_long": "前缀 + 后缀超过该链地址长度上限 {max} 位",
        "waiting": "等待生成 …", "searching": "搜 索 中 …",
        "warn": "私钥只存在于内存，关闭程序即不可恢复。请立即抄写到离线介质，不要截图外发。",
        "footer_l": "LOCAL ENGINE  ·  ZERO NETWORK CODE  ·  断网可完整使用",
        "footer_r": "python tools/audit_no_network.py",
        "export_empty": "还没有可导出的结果。",
        "export_title": "导出包含私钥",
        "export_confirm": "导出的 Excel 会包含 {n} 条私钥，文件将落在磁盘上。\n\n"
                          "这与「私钥不落盘」的设计不同，是你主动选择的结果。\n"
                          "建议导出后立即移入加密存储或离线介质，用毕安全删除。\n\n确定导出吗？",
        "export_done": "已导出 {n} 条到：\n{path}",
        "export_fail": "导出失败：\n{err}",
        "err_node": "未找到 Node.js。请安装 Node.js 18+，或把 node.exe 放到 runtime 目录。",
        "col_index": "序号", "col_chain": "链", "col_addr": "地址", "col_key": "私钥",
        "col_attempts": "尝试次数", "col_seconds": "耗时(秒)",
        "col_rule": "匹配规则", "col_time": "生成时间",
        "rule_random": "随机", "nothing": "—",
    },
    "en": {
        "title": "Vanity Generator",
        "subtitle": "VANITY ADDRESS GENERATOR  //  MULTI-CHAIN  ·  OFFLINE",
        "no_network": "NO NETWORK",
        "p1": "Match Rule", "p1_sub": "MATCH RULE",
        "prefix": "PREFIX", "suffix": "SUFFIX",
        "rules_btn": "RULES {n}",
        "rules_btn_lock": "RULES {n} · LOCKED",
        "rules_need_license": "Parallel rules need a license — only 1 rule without one",
        "rules_title": "Parallel rules",
        "rules_note": "Each rule is a prefix and/or suffix — a result is produced when ANY rule matches. "
                      "All empty means random generation.",
        "rules_add": "+ Add rule",
        "rules_add_locked": "+ Add rule · licensed only",
        "rules_apply": "APPLY",
        "rules_first": "main panel",
        "rules_col_no": "NO",
        "rules_active": "  ·  {n} rules in parallel",
        "p2": "Processor", "p2_sub": "PROCESSOR",
        "count": "COUNT", "threads": "THREADS",
        "gpu_toggle_on": "GPU · {name}",
        "gpu_toggle_off": "CPU THREADS",
        "gpu_na": "NO GPU FOUND",
        "gpu_bad_char": "Character not in this chain's alphabet; GPU cannot match it",
        "status_gpu": "GPU · {name}",
        "status_building": "Compiling GPU kernels (first run takes 2-4 min)…",
        "start": "START", "stop": "ABORT",
        "p3": "Output", "p3_sub": "OUTPUT",
        "p4": "License", "p4_sub": "LICENSE & DEVICE",
        "device_id": "DEVICE ID", "license_status": "LICENSE STATUS",
        "copy_id": "COPY ID",
        "p4_note": "A license can be bound to this device ID: send it to the issuer and the code "
                   "will only work on this machine.",
        "address": "ADDRESS", "private_key": "PRIVATE KEY",
        "copy_addr": "Copy", "show": "Show", "hide": "Hide",
        "copy_key": "Copy Key", "export": "Export XLSX",
        "attempts": "ATTEMPTS", "rate": "RATE / SEC", "elapsed": "ELAPSED", "eta": "ETA",
        "status_idle": "STANDBY", "status_init": "INITIALIZING",
        "status_run": "{n} THREADS ACTIVE",
        "status_hit": "TARGET ACQUIRED", "status_abort": "ABORTED",
        "status_error": "ERROR", "status_copy": "COPIED",
        "status_key_copy": "KEY COPIED", "status_export": "EXPORTED",
        "collected": "COLLECTED {a} / {b}",
        "credit": "CREDITS {n}",
        "credit_free": "FREE TIER",
        "credit_lock": "LICENSE",
        "credit_tampered": "LEDGER ERR",
        "credit_clock": "CLOCK ERR",
        "credit_time": "PRO UNTIL {date}",
        "credit_both": "TO {date} · {n} LEFT",
        "mid_copied": "DEVICE ID COPIED",
        "buy_btn": "Buy License",
        "buy_title": "Buy License",
        "buy_note": "Open the address below in a browser, pick a plan (your device ID is already filled in) "
                    "and the license code will be emailed to you.\nThis app has no network access and uploads nothing.",
        "buy_copy": "Copy link",
        "buy_open": "Open in browser",
        "buy_scan": "SCAN TO BUY",
        "buy_copied": "Link copied to clipboard",
        "buy_hint": "You can also scan / send this link to your phone",
        "start_confirm_title": "Confirm start",
        "cf_rules": "RULES",
        "cf_mode": "MODE",
        "cf_chain": "CHAIN",
        "cf_qty": "COUNT",
        "cf_credit": "CREDIT",
        "cf_rule_item": "rule {i}   pre {pre}   post {suf}",
        "cf_rule_more": "… {n} rules in total, all active",
        "cf_rule_none": "No rule: generates a random address",
        "cf_mode_cpu": "CPU multi-thread · {n} threads",
        "cf_mode_gpu": "GPU · {gpu} · {n} threads",
        "cf_credit_free": "Free tier · no credit used",
        "cf_credit_use": "Charges {n} credit(s) · {have} → {left}",
        "cf_credit_short": "Needs {n} credit(s), only {have} available",
        "cf_warn": "Credits are taken the moment you confirm — stopping or falling short is not refunded.",
        "cf_warn_short": "Not enough credit: you will be asked for a license code before it runs.",
        "cf_warn_free": "Fixed length is within the free tier, nothing is charged.",
        "cf_ok": "Start",
        "cf_cancel": "Cancel",
        "license_btn": "License",
        "license_title": "Enter license code",
        "license_prompt": "Paste your license code (like xxxxx.yyyyy)",
        "license_submit": "Add",
        "license_cancel": "Cancel",
        "license_empty": "Paste a license code first.",
        "license_ok_short": "ADDED +{n}",
        "need_credit": "This rule fixes {fixed} chars, beyond the free limit of {free}.\n"
                      "Needs {need} credit(s), only {have} available.",
        "credit_hint": "  ·  over {free} chars needs a license (1 credit per address)",
        "credit_charged": "Charged {n} credit(s) up front — stopped or short runs are not refunded",
        "hint_empty": "No rule · generates a random address instantly",
        "hint_bad": "Illegal character(s): {chars}",
        "hint_diff": "{n} fixed chars · ~{target} attempts · ~{eta} at current rate",
        "hint_slow": "  ·  reduce the length",
        "hint_case": "  ·  this chain is case-sensitive",
        "hint_long": "Prefix + suffix exceed the {max}-char limit",
        "waiting": "Waiting …", "searching": "SEARCHING …",
        "warn": "The private key lives in memory only; closing the app destroys it. "
                "Copy it to offline media now, never screenshot or share it.",
        "footer_l": "LOCAL ENGINE  ·  ZERO NETWORK CODE  ·  WORKS FULLY OFFLINE",
        "footer_r": "python tools/audit_no_network.py",
        "export_empty": "Nothing to export yet.",
        "export_title": "Export includes private keys",
        "export_confirm": "The XLSX will contain {n} private key(s) written to disk.\n\n"
                          "This differs from the 'no disk writes' design — your explicit choice.\n"
                          "Move it into encrypted storage or offline media, and delete "
                          "it securely when done.\n\nExport now?",
        "export_done": "Exported {n} row(s) to:\n{path}",
        "export_fail": "Export failed:\n{err}",
        "err_node": "Node.js not found. Install Node.js 18+, or drop node.exe into runtime/.",
        "col_index": "#", "col_chain": "Chain", "col_addr": "Address", "col_key": "Private Key",
        "col_attempts": "Attempts", "col_seconds": "Seconds",
        "col_rule": "Rule", "col_time": "Generated At",
        "rule_random": "random", "nothing": "—",
    },
}

LANG_LABELS = {"zh": "中文", "en": "EN"}


# ---------------------------------------------------------------- 工具

def fmt_int(n):
    return f"{int(n):,}"


def fmt_duration(seconds):
    if seconds is None:
        return "--"
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{int(seconds // 60):02d}m{int(seconds % 60):02d}s"
    return f"{seconds / 3600:.1f}h"


def human_target(target):
    if target >= 1e8:
        return f"{target / 1e8:.2f}亿"
    if target >= 1e4:
        return f"{target / 1e4:.1f}万"
    return str(int(target))


def resolve_node():
    for path in (
        os.path.join(ROOT_DIR, "runtime", "node.exe"),
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
    ):
        if os.path.isfile(path):
            return path
    return shutil.which("node")


# ---------------------------------------------------------------- 引擎进程

class EngineRunner:
    def __init__(self, on_event):
        self.on_event = on_event
        self.proc = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, chain, prefix, suffix, threads, count, rules=None):
        if self.running:
            return
        node = resolve_node()
        if not node:
            self.on_event({"t": "error", "message": "@NODE_NOT_FOUND"})
            return

        cmd = [node, ENGINE_JS,
               "--chain", chain, "--prefix", prefix, "--suffix", suffix,
               "--threads", str(threads), "--count", str(count), "--interval", "200"]
        if rules:
            cmd += ["--rules", json.dumps(rules, ensure_ascii=False)]
        flags = CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=flags, cwd=ROOT_DIR,
        )
        threading.Thread(target=self._read_loop, args=(self.proc,), daemon=True).start()

    def _read_loop(self, proc):
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.on_event(event)
        except (ValueError, OSError):
            pass
        finally:
            self.on_event({"t": "_exit", "code": proc.poll()})

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None


# ---------------------------------------------------------------- 界面

class LicenseDialog:
    """授权码输入弹窗，沿用主界面的深色配色，验签失败就地提示、不必重开"""

    def __init__(self, master, t, ledger):
        self.result = None
        self._t = t
        self._ledger = ledger

        top = tk.Toplevel(master)
        self.top = top
        top.title(t("license_title"))
        top.configure(bg=BG)
        top.resizable(False, False)
        top.transient(master)
        top.grab_set()

        w, h = 580, 250
        master.update_idletasks()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
        y = master.winfo_rooty() + 180
        top.geometry(f"{w}x{h}+{x}+{y}")

        wrap = tk.Frame(top, bg=BG, highlightbackground=CYAN_FAINT, highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(wrap, text=t("license_prompt"), bg=BG, fg=MUTED, font=F_CN,
                 anchor="w", justify="left").pack(fill="x", padx=16, pady=(14, 8))

        self.var = tk.StringVar()
        entry = tk.Entry(wrap, textvariable=self.var, bg=PANEL_FILL, fg=CYAN,
                         insertbackground=CYAN, relief="flat", font=("Consolas", 10),
                         highlightthickness=1, highlightbackground=CYAN_FAINT,
                         highlightcolor=CYAN)
        entry.pack(fill="x", padx=16, ipady=5)
        entry.focus_set()
        self.var.trace_add("write", lambda *_: self._live())

        self.tip = tk.Label(wrap, text=self._t("license_prompt"), bg=BG, fg=MUTED,
                            font=F_CN_SMALL, anchor="w", justify="left", wraplength=530)
        self.tip.pack(fill="x", padx=16, pady=(6, 0))

        row = tk.Frame(wrap, bg=BG)
        row.pack(fill="x", padx=16, pady=(10, 12))

        tk.Button(row, text=t("license_cancel"), command=self._cancel,
                  bg=BG, fg=MUTED, activebackground=BG, activeforeground=CYAN,
                  relief="flat", font=F_BTN_SM, bd=0, highlightthickness=0,
                  width=10, cursor="hand2").pack(side="right")
        tk.Button(row, text=t("license_submit"), command=self._ok,
                  bg=CYAN, fg=BG, activebackground=GREEN, activeforeground=BG,
                  relief="flat", font=("Microsoft YaHei UI", 8, "bold"), bd=0,
                  highlightthickness=0, width=12, cursor="hand2").pack(side="right", padx=(0, 8))

        entry.bind("<Return>", lambda _e: self._ok())
        top.bind("<Escape>", lambda _e: self._cancel())
        top.protocol("WM_DELETE_WINDOW", self._cancel)

        top.wait_window()

    def _live(self):
        """输入 / 粘贴后即时诊断授权码结构，不用等点「导入」"""
        state, msg = lic.describe_code(self.var.get())
        color = {"empty": MUTED, "ok": GREEN}.get(state, AMBER)
        self.tip.configure(text=msg, fg=color)

    def _ok(self):
        code = self.var.get().strip()
        if not code:
            self.tip.configure(text=self._t("license_empty"), fg=RED)
            return
        try:
            self._ledger.add_code(code)
        except lic.LicenseError as exc:
            self.tip.configure(text=str(exc), fg=RED)
            return
        self.result = code
        self.top.destroy()

    def _cancel(self):
        self.result = None
        self.top.destroy()


class StartConfirmDialog:
    """开跑前的确认窗：匹配规则、运算模式、数量、扣多少额度，一次讲清楚再开"""

    def __init__(self, master, t, rows, warn, warn_color, ok_label):
        self.ok = False
        top = tk.Toplevel(master)
        self.top = top
        top.title(t("start_confirm_title"))
        top.configure(bg=BG)
        top.resizable(False, False)
        top.transient(master)
        top.grab_set()

        wrap = tk.Frame(top, bg=BG, highlightbackground=CYAN_FAINT,
                        highlightthickness=1, width=660)
        wrap.pack(fill="both", expand=True, padx=10, pady=10)

        for idx, (label, value, color) in enumerate(rows):
            row = tk.Frame(wrap, bg=BG)
            row.pack(fill="x", padx=16, pady=(12 if idx == 0 else 0, 6))
            tk.Label(row, text=label, bg=BG, fg=CYAN_DIM, font=F_LABEL,
                     anchor="w", width=10).pack(side="left")
            tk.Label(row, text=value, bg=BG, fg=color, font=F_CN_SMALL, anchor="w",
                     justify="left", wraplength=486).pack(side="left", fill="x", expand=True)

        tk.Label(wrap, text=warn, bg=BG, fg=warn_color, font=F_CN_SMALL, anchor="w",
                 justify="left", wraplength=604).pack(fill="x", padx=16, pady=(6, 0))

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(fill="x", padx=16, pady=(14, 12))

        tk.Button(foot, text=t("cf_cancel"), command=self._cancel,
                  bg=BG, fg=MUTED, activebackground=BG, activeforeground=CYAN,
                  relief="flat", font=F_BTN_SM, bd=0, highlightthickness=0,
                  width=10, cursor="hand2").pack(side="right")
        tk.Button(foot, text=ok_label, command=self._ok,
                  bg=CYAN, fg=BG, activebackground=GREEN, activeforeground=BG,
                  relief="flat", font=("Microsoft YaHei UI", 8, "bold"), bd=0,
                  highlightthickness=0, width=14, cursor="hand2").pack(side="right", padx=(0, 8))

        top.bind("<Escape>", lambda _e: self._cancel())
        top.bind("<Return>", lambda _e: self._ok())
        top.protocol("WM_DELETE_WINDOW", self._cancel)

        # 内容自撑尺寸，再摆到主窗中间
        top.update_idletasks()
        w = max(660, top.winfo_reqwidth())
        h = top.winfo_reqheight()
        master.update_idletasks()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
        y = master.winfo_rooty() + 110
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.focus_set()

        top.wait_window()

    def _ok(self):
        self.ok = True
        self.top.destroy()

    def _cancel(self):
        self.ok = False
        self.top.destroy()


class RuleEditor:
    """多规则编辑窗口：每条规则 = 前缀 + 后缀，命中任意一条即产出结果

    多规则并行是付费功能：没有有效授权时只能留 1 条，无法添加。
    """

    MAX_RULES = 32

    def __init__(self, app):
        self.app = app
        self.t = app.t
        self.max_rules = self.MAX_RULES if app._multi_rules_allowed() else 1
        top = tk.Toplevel(app.root)
        self.top = top
        top.title(self.t("rules_title"))
        top.configure(bg=BG)
        top.resizable(False, False)
        top.transient(app.root)
        top.grab_set()

        w, h = 720, 430
        app.root.update_idletasks()
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width() - w) // 2)
        y = app.root.winfo_rooty() + 120
        top.geometry(f"{w}x{h}+{x}+{y}")

        wrap = tk.Frame(top, bg=BG, highlightbackground=CYAN_FAINT, highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(wrap, text=self.t("rules_note"), bg=BG, fg=MUTED, font=F_CN_SMALL,
                 anchor="w", justify="left", wraplength=650).pack(fill="x", padx=16, pady=(12, 4))

        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x", padx=16, pady=(6, 2))
        for text, width in ((self.t("rules_col_no"), 4), (self.t("prefix"), 18),
                            (self.t("suffix"), 18)):
            tk.Label(head, text=text, bg=BG, fg=DIM, font=F_CN_SMALL, width=width,
                     anchor="w").pack(side="left")

        scroll = tk.Frame(wrap, bg=BG)
        scroll.pack(fill="both", expand=True, padx=(16, 8))

        self.canvas_rows = tk.Canvas(scroll, bg=BG, highlightthickness=0, height=246)
        self.sb = tk.Scrollbar(scroll, orient="vertical", command=self.canvas_rows.yview)
        self.canvas_rows.configure(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y", padx=(8, 0))
        self.canvas_rows.pack(side="left", fill="both", expand=True)

        self.rows_box = tk.Frame(self.canvas_rows, bg=BG)
        self._rows_win = self.canvas_rows.create_window((0, 0), window=self.rows_box,
                                                        anchor="nw")
        self.rows_box.bind("<Configure>", self._resize_rows)
        self.canvas_rows.bind("<Configure>", self._resize_rows)

        def wheel(event):
            self.canvas_rows.yview_scroll(-1 if event.delta > 0 else 1, "units")

        self.canvas_rows.bind("<MouseWheel>", wheel)
        self.rows_box.bind("<MouseWheel>", wheel)

        self.rows = []
        for r in app._all_rules():
            self._add_row(r["prefix"], r["suffix"])

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(fill="x", padx=16, pady=(8, 12))

        self.btn_add = tk.Button(foot, text=self.t("rules_add"), command=self._add_blank,
                                 bg=BG, fg=CYAN, activebackground=BG, activeforeground=CYAN,
                                 relief="flat", font=F_BTN_SM, bd=0, highlightthickness=1,
                                 highlightbackground=CYAN_FAINT, cursor="hand2", width=14)
        self.btn_add.pack(side="left")

        tk.Button(foot, text=self.t("license_cancel"), command=self.top.destroy,
                  bg=BG, fg=MUTED, activebackground=BG, activeforeground=CYAN,
                  relief="flat", font=F_BTN_SM, bd=0, highlightthickness=0,
                  width=10, cursor="hand2").pack(side="right", padx=(8, 0))
        tk.Button(foot, text=self.t("rules_apply"), command=self._save,
                  bg=CYAN_FAINT, fg=CYAN, activebackground=CYAN_DIM, activeforeground="#FFFFFF",
                  relief="flat", font=F_BTN_SM, bd=0, highlightthickness=0,
                  width=12, cursor="hand2").pack(side="right", padx=(8, 0))

        self._refresh_add_btn()
        self._resize_rows()

    # ----------

    def _resize_rows(self, _e=None):
        self.canvas_rows.configure(scrollregion=self.canvas_rows.bbox("all"))
        self.canvas_rows.itemconfigure(self._rows_win, width=self.canvas_rows.winfo_width())

    def _refresh_add_btn(self):
        if self.max_rules <= 1:
            # 未授权：按钮可点，点了先要授权码；拿到有效授权后自动解锁
            self.btn_add.configure(text=self.t("rules_add_locked"), state="normal",
                                   fg=AMBER)
            return
        full = len(self.rows) >= self.max_rules
        self.btn_add.configure(text=self.t("rules_add"),
                               state="disabled" if full else "normal",
                               fg=DIM if full else CYAN)

    def _add_blank(self):
        if len(self.rows) >= self.max_rules:
            if self.max_rules <= 1:
                self.app._ask_license()
                self.max_rules = (self.MAX_RULES
                                  if self.app._multi_rules_allowed() else 1)
                self._refresh_add_btn()
            return
        self._add_row("", "")
        self._refresh_add_btn()

    def _add_row(self, prefix="", suffix=""):
        box = tk.Frame(self.rows_box, bg=BG)
        box.pack(fill="x", pady=3, padx=(0, 6))
        no = len(self.rows) + 1

        tk.Label(box, text=str(no), bg=BG, fg=CYAN, font=("Consolas", 11, "bold"),
                 width=4, anchor="w").pack(side="left")

        pv = tk.StringVar(value=prefix)
        ev_p = tk.Entry(box, textvariable=pv, bg=PANEL_FILL, fg=CYAN, insertbackground=CYAN,
                        relief="flat", font=("Consolas", 11), highlightthickness=1,
                        highlightbackground=CYAN_FAINT, highlightcolor=CYAN)
        ev_p.pack(side="left", ipady=3, padx=(0, 14))

        sv = tk.StringVar(value=suffix)
        ev_s = tk.Entry(box, textvariable=sv, bg=PANEL_FILL, fg=CYAN, insertbackground=CYAN,
                        relief="flat", font=("Consolas", 11), highlightthickness=1,
                        highlightbackground=CYAN_FAINT, highlightcolor=CYAN)
        ev_s.pack(side="left", ipady=3)

        entry = (box, pv, sv)
        self.rows.append(entry)

        if no > 1:
            tk.Button(box, text="×", command=lambda e=entry: self._remove(e),
                      bg=BG, fg=RED, activebackground=BG, activeforeground=RED,
                      relief="flat", font=("Consolas", 12, "bold"), bd=0,
                      highlightthickness=0, width=3, cursor="hand2").pack(side="right")
        else:
            tk.Label(box, text=self.t("rules_first"), bg=BG, fg=DIM,
                     font=F_CN_SMALL).pack(side="right", padx=(6, 0))

        ev_p.focus_set()

    def _remove(self, entry):
        box = entry[0]
        self.rows.remove(entry)
        box.destroy()
        self._renumber()
        self._refresh_add_btn()

    def _renumber(self):
        for i, (box, _pv, _sv) in enumerate(self.rows):
            for child in box.winfo_children():
                if isinstance(child, tk.Label) and child.cget("text").isdigit():
                    child.configure(text=str(i + 1))
                    break

    def _save(self):
        data = []
        for _box, pv, sv in self.rows:
            p, s = pv.get().strip(), sv.get().strip()
            if not p and not s and data:
                continue      # 附加的空白行直接丢掉
            data.append({"prefix": p, "suffix": s})
        self.app._apply_rules(data)
        self.top.destroy()


class HUDApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events = queue.Queue()
        self.runner = EngineRunner(self.events.put)
        self.gpu_runner = gpu_engine.GpuRunner(self.events.put)
        self.active = self.runner

        self.gpu_info = gpu_engine.gpu_summary()
        # 上次关掉软件时的设置（规则、链、语言、线程、数量、GPU）原样恢复
        self._state = state_store.load()
        # 默认走 CPU；用户在界面点 GPU 按钮才启用显卡
        self.use_gpu = bool(self._state.get("use_gpu")) and bool(self.gpu_info)

        self.lang = self._state["lang"] if self._state["lang"] in I18N else "zh"
        self.chain = self._state["chain"] if self._state["chain"] in CHAINS else "eth"
        self.threads = self._state["threads"] or self._default_threads()
        self.count = max(1, int(self._state["count"]))

        # 多规则并行：主面板的两个输入框是「规则 1」，这里是第 2 条及以后
        saved_rules = self._state.get("rules") or [{"prefix": "", "suffix": ""}]
        self._seed_rule = dict(saved_rules[0])
        self.extra_rules = [dict(r) for r in saved_rules[1:]]
        self.rules_snapshot = []

        # 运行状态
        self.running = False
        self.attempts = 0
        self.rate = 0
        self.elapsed = 0.0
        self.eta = None
        self.target = 1
        self.collected = 0
        self.want = 1
        self.results = []
        self.latest = None
        self.reveal = False

        self.license = lic.Ledger()
        self.reserved = 0

        # 动画状态
        self.phase = 0.0
        self.scan_y = 0.0
        self.flow_x = 0.0
        self.blink = 0
        self.typewriter = 0
        self.full_addr = ""

        self.buttons = []
        self.entries = {}
        self.dropdowns = {}
        self.dyn = {}

        self._build_window()
        self._rebuild()
        self.root.after(40, self._tick)

    # ---------- 语言 / 链

    def t(self, key, **kw):
        text = I18N[self.lang].get(key, key)
        return text.format(**kw) if kw else text

    def meta(self):
        return chain_meta(self.chain)

    def _tw(self, text):
        """粗略文本宽度（中文按 2 个西文字符宽计），用于标签排版"""
        return sum(12 if ord(ch) > 127 else 7 for ch in text)

    # ---------- 窗口

    def _default_threads(self):
        try:
            return max(1, os.cpu_count() or 4)
        except Exception:
            return 4

    def _build_window(self):
        self.root.title("靓号生成器")
        self.root.configure(bg=BG)
        w, h = int(S(DESIGN_W)), int(S(DESIGN_H))
        self.root.geometry(f"{w}x{h}")
        self.root.resizable(False, False)
        self.canvas = tk.Canvas(self.root, width=w, height=h, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)

    # ---------- 图元

    def _line(self, x1, y1, x2, y2, color, width=1):
        return self.canvas.create_line(S(x1), S(y1), S(x2), S(y2), fill=color,
                                       width=max(1, int(S(width))), capstyle="butt")

    def _rect(self, x1, y1, x2, y2, outline, fill="", width=1):
        return self.canvas.create_rectangle(S(x1), S(y1), S(x2), S(y2),
                                            outline=outline, fill=fill,
                                            width=max(1, int(S(width))))

    def _text(self, x, y, text, font, color, anchor="nw", **kw):
        return self.canvas.create_text(S(x), S(y), text=text, font=font,
                                       fill=color, anchor=anchor, **kw)

    def _corners(self, x1, y1, x2, y2, size=16, color=CYAN_DIM):
        for cx, cy, dx, dy in ((x1, y1, 1, 1), (x2, y1, -1, 1),
                               (x1, y2, 1, -1), (x2, y2, -1, -1)):
            self._line(cx, cy, cx + dx * size, cy, color)
            self._line(cx, cy, cx, cy + dy * size, color)

    def _panel(self, x1, y1, x2, y2, index, title, subtitle=""):
        self._rect(x1, y1, x2, y2, CYAN_FAINT, fill=PANEL_FILL, width=1)
        self._rect(x1 + 2, y1 + 2, x2 - 2, y2 - 2, "#0B1B26", width=1)
        self._corners(x1, y1, x2, y2)
        self._text(x1 + 16, y1 + 14, f"[ {index} ]", F_LABEL, CYAN)
        self._text(x1 + 62, y1 + 13, title, F_CN, TEXT)
        if subtitle:
            self._text(x1 + 70 + self._tw(title), y1 + 14, subtitle, F_LABEL, DIM)

    # ---------- 按钮 / 下拉

    def _button(self, x1, y1, x2, y2, label, kind, cmd, font=None):
        btn = {"rect": (x1, y1, x2, y2), "label": label, "kind": kind, "cmd": cmd,
               "enabled": True, "hover": False, "font": font or F_BTN}
        btn["ids"] = self._draw_button(btn)
        self.buttons.append(btn)
        return btn

    def _draw_button(self, btn):
        x1, y1, x2, y2 = btn["rect"]
        enabled, hover = btn["enabled"], btn["hover"] and btn["enabled"]
        kind = btn["kind"]
        if kind == "primary":
            fill = CYAN if enabled else "#0A2530"
            fg = BG if enabled else "#3D7E90"
            fill = "#7CF0FF" if hover else fill
        elif kind == "danger":
            fill = "#2A0E14" if enabled else "#12181C"
            fg = RED if enabled else "#38505E"
            fill = "#3D1420" if (hover and enabled) else fill
        else:
            fill = "#0A1822" if enabled else "#081016"
            fg = TEXT if enabled else "#38505E"
            fill = "#12262F" if (hover and enabled) else fill
        ids = [self.canvas.create_rectangle(
            S(x1), S(y1), S(x2), S(y2), fill=fill,
            outline=CYAN if (kind == "primary" and enabled) else "#123040",
            width=max(1, int(S(1))),
        )]
        ids.append(self._text((x1 + x2) / 2, (y1 + y2) / 2 + 1, btn["label"],
                              btn["font"], fg, anchor="center"))
        return ids

    def _redraw_button(self, btn):
        for i in btn["ids"]:
            self.canvas.delete(i)
        btn["ids"] = self._draw_button(btn)

    def _set_enabled(self, btn, enabled):
        if btn["enabled"] == enabled:
            return
        btn["enabled"] = enabled
        self._redraw_button(btn)

    def _dropdown(self, dkey, x1, y1, x2, y2, text):
        ids = [self._rect(x1, y1, x2, y2, "#0E3040", fill="#07121B", width=1),
               self._text(x1 + 8, (y1 + y2) / 2, text, F_DD, CYAN, anchor="w"),
               self._text(x2 - 8, (y1 + y2) / 2, "▾", F_DD, CYAN_DIM, anchor="e")]
        self.dropdowns[dkey] = {"rect": (x1, y1, x2, y2), "ids": ids,
                                "open": False, "item_ids": [], "option_rects": []}

    def _dropdown_options(self, dkey):
        if dkey == "lang":
            return [("zh", "中文"), ("en", "EN")]
        return [(cid, f"{CHAINS[cid]['tag']}  ·  {CHAINS[cid]['name']}") for cid in CHAIN_ORDER]

    def _set_entries_visible(self, visible, box=None):
        """嵌入式 Entry 永远画在 Canvas 之上：展开下拉时把与之重叠的输入框临时藏起"""
        for entry in self.entries.values():
            win_id = getattr(entry, "_win_id", None)
            if win_id is None:
                continue
            if not visible and box is not None:
                eb = getattr(entry, "_box", None)
                if not eb or not (eb[0] < box[2] and eb[2] > box[0]
                                  and eb[1] < box[3] and eb[3] > box[1]):
                    continue
            try:
                self.canvas.itemconfigure(win_id, state="normal" if visible else "hidden")
            except tk.TclError:
                pass

    def _open_dropdown(self, dkey):
        for k, d in self.dropdowns.items():
            if d["open"]:
                self._close_dropdown(k)

        d = self.dropdowns[dkey]
        options = self._dropdown_options(dkey)
        cur = self.lang if dkey == "lang" else self.chain
        x1, y1, x2, y2 = d["rect"]
        item_h = 22
        top = y2 + 2
        self._set_entries_visible(False, (x1, top, x2, top + item_h * len(options) + 2))

        # 遮罩式面板
        d["item_ids"].append(self._rect(x1, top, x2, top + item_h * len(options) + 2,
                                        CYAN_DIM, fill="#050C15", width=1))
        for i, (value, label) in enumerate(options):
            ry = top + 2 + i * item_h
            is_cur = value == cur
            if is_cur:
                # 只画左侧指示条，避免整块底色压住文字
                d["item_ids"].append(self._rect(x1 + 2, ry + 3, x1 + 5, ry + item_h - 5,
                                                CYAN, fill=CYAN, width=1))
            tid = self._text(x1 + 12, ry + item_h / 2 - 1, label, F_DD,
                             CYAN if is_cur else TEXT, anchor="w")
            d["item_ids"].append(tid)
            self.canvas.tag_raise(tid)
            d["option_rects"].append((x1 + 2, ry, x2 - 2, ry + item_h - 2))
        d["item_ids"].append(self._rect(x1, top, x2, top + item_h * len(options) + 2,
                                        CYAN_DIM, width=1))
        d["open"] = True

    def _close_dropdown(self, dkey):
        d = self.dropdowns[dkey]
        for i in d["item_ids"]:
            self.canvas.delete(i)
        d["item_ids"] = []
        d["option_rects"] = []
        d["open"] = False
        self._set_entries_visible(True)

    def _choose_option(self, dkey, index):
        value = self._dropdown_options(dkey)[index][0]
        self._close_dropdown(dkey)
        if dkey == "lang":
            if value != self.lang:
                self.lang = value
                self._rebuild()
                self._save_state()
        else:
            if value != self.chain and not self.running:
                self.chain = value
                self._rebuild()
                self._save_state()

    # ---------- 重绘

    def _rebuild(self):
        first = not self.entries          # 首次建界面：用 state 里记住的值，不要被空值覆盖
        values = {} if first else self._collect_values()
        for entry in self.entries.values():
            try:
                entry.destroy()
            except tk.TclError:
                pass

        self.canvas.delete("all")
        self.buttons = []
        self.entries = {}
        self.dropdowns = {}
        self.dyn = {}

        self._draw_static()
        self._make_widgets()
        self._apply_values(values)
        self._refresh_hint()
        self._restore_display()

    def _draw_static(self):
        for x in range(0, DESIGN_W + 1, 28):
            self._line(x, 0, x, DESIGN_H, GRID_BRIGHT if x % 112 == 0 else GRID, 1)
        for y in range(0, DESIGN_H + 1, 28):
            self._line(0, y, DESIGN_W, y, GRID_BRIGHT if y % 112 == 0 else GRID, 1)

        self._line(0, 96, 96, 0, CYAN_FAINT, 2)
        self._line(DESIGN_W - 96, 0, DESIGN_W, 96, CYAN_FAINT, 2)
        self._line(0, DESIGN_H - 60, 60, DESIGN_H, CYAN_FAINT, 2)

        # 顶栏
        self._rect(28, 24, 31, 60, CYAN, fill=CYAN, width=1)
        self._text(44, 24, self.t("title"), F_TITLE, TEXT)
        self._text(46, 58, self.t("subtitle"), F_SUB, MUTED)
        self._text(46, 72, f"[ {self.meta()['tag']} ]  {self.meta()['name']}", F_LABEL, CYAN_DIM)

        self._dropdown("chain", 598, 22, 790, 52, f"{self.meta()['tag']}  ▾")
        self._dropdown("lang", 800, 22, 930, 52, f"{LANG_LABELS[self.lang]}  ▾")

        # 顶部右：状态灯 + 无网络
        self._text(920, 66, self.t("no_network"), F_CN_SMALL, CYAN_DIM, anchor="e")

        for x in range(28, DESIGN_W - 28, 16):
            self._line(x, 88, x + 10, 88, CYAN_FAINT if x % 32 == 0 else "#0E1A24", 2)

        # 面板
        self._panel(28, 104, DESIGN_W - 28, 250, "01", self.t("p1"), self.t("p1_sub"))
        self._panel(28, 264, DESIGN_W - 28, 458, "02", self.t("p2"), self.t("p2_sub"))
        self._panel(28, 472, DESIGN_W - 28, 682, "03", self.t("p3"), self.t("p3_sub"))
        self._panel(28, 696, DESIGN_W - 28, 812, "04", self.t("p4"), self.t("p4_sub"))

        # 面板 01
        self._text(48, 142, self.t("prefix"), F_CN, MUTED)
        self._text(48 + self._tw(self.t("prefix")) + 8, 143, "PREFIX" if self.lang == "zh" else "",
                    F_LABEL, DIM)
        self._text(360, 142, self.t("suffix"), F_CN, MUTED)
        self._text(360 + self._tw(self.t("suffix")) + 8, 143, "SUFFIX" if self.lang == "zh" else "",
                    F_LABEL, DIM)
        self._line(48, 193, 336, 193, CYAN_DIM, 1)
        self._line(360, 193, 648, 193, CYAN_DIM, 1)

        # 面板 02：数量 / 线程 / CPU·GPU 切换 / 开始 / 中止 同排
        self._text(48, 296, self.t("count"), F_CN, MUTED)
        self._text(150, 296, self.t("threads"), F_CN, MUTED)
        self._line(48, 346, 138, 346, CYAN_DIM, 1)

        self._rect(48, BAR_Y1, 932, BAR_Y2, "#10202B", fill="#070E16", width=1)
        for i in range(1, 10):
            x = 48 + (932 - 48) * i / 10
            self._line(x, BAR_Y1 + 2, x, BAR_Y2 - 2, "#16303C", 1)

        stats = [(48, "attempts"), (274, "rate"), (500, "elapsed"), (726, "eta")]
        for x, key in stats:
            self._text(x, 398, self.t(key).upper() if self.lang == "en" else self.t(key),
                       F_CN_SMALL if self.lang == "zh" else F_LABEL, CYAN_DIM)

        # 面板 03
        self._text(48, 506, self.t("address"), F_CN, MUTED)
        self._text(48, 566, self.t("private_key"), F_CN, MUTED)

        self._rect(48, 642, 932, 674, "#2A1D06", fill="#150F04", width=1)
        self._text(58, 658, self.t("warn"), F_CN_SMALL, AMBER)

        # 面板 04：设备 ID（黄）+ 授权状态 + 授权码
        self._text(48, 722, self.t("device_id"), F_CN, MUTED)
        self._text(400, 722, self.t("license_status"), F_CN, MUTED)
        self._text(48, 786, self.t("p4_note"), F_CN_SMALL, MUTED)

        # 底部
        self._line(28, 826, DESIGN_W - 28, 826, "#0C1A24", 1)
        self._text(28, 838, self.t("footer_l"), F_LABEL, DIM)
        self._text(DESIGN_W - 28, 838, self.t("footer_r"), F_LABEL, DIM, anchor="ne")

        self._init_dynamic()

    def _init_dynamic(self):
        c = self.canvas
        self.dyn["scan"] = c.create_line(S(0), S(self.scan_y), S(DESIGN_W), S(self.scan_y),
                                         fill="#0A2634", width=max(1, int(S(2))))
        self.dyn["led"] = c.create_oval(S(838), S(61), S(848), S(71), fill=CYAN, outline="")
        self.dyn["bar_fill"] = c.create_rectangle(S(48), S(BAR_Y1), S(48), S(BAR_Y2),
                                                  fill=CYAN, outline="")
        self.dyn["bar_glow"] = c.create_rectangle(S(48), S(BAR_Y1), S(48), S(BAR_Y2),
                                                  fill="#8FF4FF", outline="")
        self.dyn["attempts"] = self._text(48, STAT_Y, "--", F_NUM, TEXT)
        self.dyn["rate"] = self._text(274, STAT_Y, "--", F_NUM, TEXT)
        self.dyn["elapsed"] = self._text(500, STAT_Y, "--", F_NUM, TEXT)
        self.dyn["eta"] = self._text(726, STAT_Y, "--", F_NUM, TEXT)
        # 面板 04：授权状态（右）+ 设备 ID（黄色）
        self.dyn["credit"] = self._text(400, 741, "", F_CN, MUTED)
        self.dyn["mid"] = self._text(48, 742, "", ("Consolas", 12, "bold"), AMBER)
        self.canvas.tag_bind(self.dyn["mid"], "<Button-1>", lambda _e: self._copy_mid())
        # 面板 02：控制行右端的运行状态
        self.dyn["status"] = self._text(932, 330, self.t("status_idle"), F_LABEL, MUTED, anchor="e")
        self.dyn["addr"] = self._text(48, 520, self.t("waiting"), F_ADDR, DIM)
        self.dyn["key"] = self._text(48, 584, self.t("nothing"), F_KEY, DIM)
        self.dyn["collected"] = self._text(48, 616, self.t("collected", a=0, b=self.want),
                                           F_LABEL, MUTED)
        self.dyn["hint"] = self._text(48, 226, "", F_CN_SMALL, MUTED)

    # ---------- 控件

    def _make_widgets(self):
        self.entries["prefix"] = self._entry(48, 162, 288, 30,
                                             "例如 8888" if self.lang == "zh" else "e.g. 8888",
                                             default=self._seed_rule.get("prefix", ""))
        self.entries["suffix"] = self._entry(360, 162, 288, 30,
                                             "例如 cafe" if self.lang == "zh" else "e.g. cafe",
                                             default=self._seed_rule.get("suffix", ""))
        self.entries["count"] = self._entry(48, 316, 86, 28, "", default=str(self.count))
        for key in ("prefix", "suffix", "count"):
            self.entries[key].bind("<FocusOut>", lambda _e: self._save_state(), add="+")

        # 面板 01 右端：多规则入口
        self.btn_rules = self._button(660, 158, 932, 192, self._rules_label(), "ghost",
                                      self._edit_rules, F_BTN_SM)

        self.btn_thr_minus = self._button(150, 316, 182, 344, "−", "ghost",
                                          lambda: self._nudge_threads(-4), F_BTN_SM)
        self.dyn["threads"] = self._text(198, 330, str(self.threads),
                                         ("Consolas", 13, "bold"), CYAN, anchor="center")
        self.btn_thr_plus = self._button(214, 316, 246, 344, "+", "ghost",
                                         lambda: self._nudge_threads(4), F_BTN_SM)

        self.btn_gpu = self._button(258, 312, 478, 350, self._gpu_label(), "ghost",
                                    self._toggle_gpu, F_BTN_SM)
        if not self.gpu_info:
            self._set_enabled(self.btn_gpu, False)
        self._apply_threads_display()

        self.btn_start = self._button(490, 312, 612, 350, self.t("start"), "primary", self._on_start)
        self.btn_stop = self._button(624, 312, 744, 350, self.t("stop"), "danger", self._on_stop)
        self.btn_stop["enabled"] = False
        self._redraw_button(self.btn_stop)

        # 面板 04：授权码 + 复制设备 ID + 购买授权码
        self.btn_license = self._button(812, 730, 932, 762, self.t("license_btn"), "primary",
                                        self._on_license, F_BTN_SM)
        self.btn_buy = self._button(662, 730, 800, 762, self.t("buy_btn"), "ghost",
                                    self._on_buy, F_BTN_SM)
        self.btn_copy_id = self._button(296, 730, 380, 762, self.t("copy_id"), "ghost",
                                        self._copy_mid, F_BTN_SM)

        self.btn_copy_addr = self._button(846, 512, 932, 538, self.t("copy_addr"), "ghost",
                                          lambda: self._copy(self.full_addr), F_BTN_SM)
        self.btn_reveal = self._button(790, 570, 856, 596, self.t("show"), "ghost",
                                       self._toggle_reveal, F_BTN_SM)
        self.btn_copy_key = self._button(866, 570, 932, 596, self.t("copy_key"), "ghost",
                                         self._copy_secret, F_BTN_SM)
        self.btn_export = self._button(766, 604, 932, 634, self.t("export"), "primary",
                                       self._on_export, F_BTN_SM)
        for b in (self.btn_copy_addr, self.btn_reveal, self.btn_copy_key):
            self._set_enabled(b, False)
        self._set_enabled(self.btn_export, bool(self.results))

    def _entry(self, x, y, width, height, placeholder, default=""):
        var = tk.StringVar()
        entry = tk.Entry(self.canvas, textvariable=var, bg=ENTRY_BG, fg=CYAN,
                         insertbackground=CYAN, relief="flat", bd=0,
                         highlightthickness=0, font=("Consolas", 13))
        entry._var = var
        entry._placeholder = placeholder
        if default:
            var.set(default)
        elif placeholder:
            var.set(placeholder)
            entry.configure(fg=DIM)

        entry._win_id = self.canvas.create_window(S(x), S(y), window=entry, anchor="nw",
                                                  width=S(width), height=S(height))
        entry._box = (x, y, x + width, y + height)

        def on_focus_in(_e):
            if placeholder and var.get() == placeholder:
                var.set("")
            entry.configure(fg=CYAN)

        def on_focus_out(_e=None):
            if placeholder and not var.get():
                var.set(placeholder)
                entry.configure(fg=DIM)

        entry.bind("<FocusIn>", on_focus_in, add="+")
        entry.bind("<FocusOut>", on_focus_out, add="+")
        entry.bind("<KeyRelease>", lambda e: self._refresh_hint(), add="+")
        return entry

    def _entry_value(self, key, raw=False):
        entry = self.entries.get(key)
        if entry is None:
            return ""
        value = entry._var.get()
        if not raw and entry._placeholder and value == entry._placeholder:
            return ""
        return value

    def _collect_values(self):
        return {
            "prefix": self._entry_value("prefix"),
            "suffix": self._entry_value("suffix"),
            "count": self._entry_value("count", raw=True),
        }

    def _apply_values(self, values):
        for key, val in values.items():
            entry = self.entries.get(key)
            if entry is None:
                continue
            if val:
                entry._var.set(val)
                entry.configure(fg=CYAN)
            elif entry._placeholder:
                entry._var.set(entry._placeholder)
                entry.configure(fg=DIM)

    # ---------- 状态记忆

    def _safe_count(self):
        try:
            return max(1, int(str(self._entry_value("count", raw=True)).strip() or "1"))
        except (TypeError, ValueError):
            return 1

    def _save_state(self):
        """把当前规则/链/语言/线程/数量/GPU 写盘，下次打开原样恢复"""
        try:
            rules = self._all_rules()
        except Exception:
            rules = self._state.get("rules") or [{"prefix": "", "suffix": ""}]
        self._state.update({
            "lang": self.lang,
            "chain": self.chain,
            "threads": self.threads,
            "count": self._safe_count(),
            "use_gpu": bool(self.use_gpu),
            "rules": rules,
        })
        state_store.save(self._state)

    def _nudge_threads(self, delta):
        if self.running:
            return
        self.threads = max(1, min(256, self.threads + delta))
        if "threads" in self.dyn:
            self.canvas.itemconfig(self.dyn["threads"], text=str(self.threads))
        self._save_state()

    # ---------- GPU 开关

    def _gpu_label(self):
        if not self.gpu_info:
            return self.t("gpu_na")
        if self.use_gpu:
            return self.t("gpu_toggle_on", name=self.gpu_info["name"].replace("NVIDIA GeForce ", ""))
        return self.t("gpu_toggle_off")

    def _toggle_gpu(self):
        if self.running or not self.gpu_info:
            return
        self.use_gpu = not self.use_gpu
        self.btn_gpu["label"] = self._gpu_label()
        self._redraw_button(self.btn_gpu)
        self._apply_threads_display()
        self._refresh_hint()
        self._save_state()

    def _apply_threads_display(self):
        """GPU 模式下线程数无意义，显示占位并禁用 ± 按钮"""
        gpu_mode = bool(self.gpu_info) and self.use_gpu
        if "threads" in self.dyn:
            self.canvas.itemconfig(self.dyn["threads"],
                                   text="—" if gpu_mode else str(self.threads))
        for btn in (getattr(self, "btn_thr_minus", None), getattr(self, "btn_thr_plus", None)):
            if btn is not None:
                self._set_enabled(btn, not gpu_mode)

    # ---------- 多规则并行

    def _multi_rules_allowed(self):
        """多规则并行需要有效授权；没有授权只能匹配 1 条规则"""
        try:
            return bool(self.license.licensed())
        except Exception:
            return False

    def _all_rules(self):
        """规则集合：第 1 条来自主面板输入框，其余来自规则编辑器"""
        meta = self.meta()
        p = self._entry_value("prefix").strip()
        s = self._entry_value("suffix").strip()
        if meta["is_evm"]:
            p = p.replace("0x", "").replace("0X", "").lower()
            s = s.replace("0x", "").replace("0X", "").lower()
        rules = [{"prefix": p, "suffix": s}]
        for r in self.extra_rules:
            pp = str(r.get("prefix", ""))
            ss = str(r.get("suffix", ""))
            if meta["is_evm"]:
                pp = pp.replace("0x", "").replace("0X", "").lower()
                ss = ss.replace("0x", "").replace("0X", "").lower()
            rules.append({"prefix": pp, "suffix": ss})
        return rules

    def _effective_rules(self):
        """去掉全空白的规则（全空白 = 随机生成）"""
        return [r for r in self._all_rules() if r["prefix"] or r["suffix"]]

    def _rule_total(self):
        return 1 + len(self.extra_rules)

    def _rules_label(self):
        n = self._rule_total()
        if n > 1 and not self._multi_rules_allowed():
            return self.t("rules_btn_lock", n=n)
        return self.t("rules_btn", n=n)

    def _refresh_rules_btn(self):
        if getattr(self, "btn_rules", None) is None:
            return
        self.btn_rules["label"] = self._rules_label()
        self._redraw_button(self.btn_rules)

    def _apply_rules(self, rules):
        rules = rules or [{"prefix": "", "suffix": ""}]
        self._apply_values({"prefix": rules[0].get("prefix", ""),
                            "suffix": rules[0].get("suffix", "")})
        self.extra_rules = [{"prefix": r.get("prefix", ""), "suffix": r.get("suffix", "")}
                            for r in rules[1:]]
        self._refresh_rules_btn()
        self._refresh_hint()
        self._save_state()

    def _edit_rules(self):
        if self.running:
            return
        RuleEditor(self)

    # ---------- 提示 / 难度

    def _refresh_hint(self):
        if "hint" not in self.dyn:
            return
        meta = self.meta()
        rules = self._effective_rules()

        if not rules:
            self.canvas.itemconfig(self.dyn["hint"], text=self.t("hint_empty"), fill=MUTED)
            self._refresh_credit()
            return

        bad = [ch for r in rules for ch in r["prefix"] + r["suffix"]
               if ch not in meta["alphabet"]]
        if bad:
            c = self.canvas
            c.itemconfig(self.dyn["hint"],
                         text=self.t("hint_bad", chars=" ".join(sorted(set(bad)))),
                         fill=RED)
            return

        over = [r for r in rules
                if len(r["prefix"]) + len(r["suffix"]) > meta["maxlen"]]
        if over:
            self.canvas.itemconfig(self.dyn["hint"],
                                   text=self.t("hint_long", max=meta["maxlen"]), fill=RED)
            return

        # 多规则并行：命中概率相加，等价期望次数 = 1 / Σ(1/单条期望)
        targets = []
        for r in rules:
            fixed = len(r["prefix"]) + len(r["suffix"])
            targets.append(1 if fixed == 0 else meta["base"] ** fixed)
        target = max(1, 1 / sum(1 / t for t in targets))
        n = max(len(r["prefix"]) + len(r["suffix"]) for r in rules)

        gpu_mode = bool(self.gpu_info) and self.use_gpu
        # GPU 实测：EVM 约 1.3e7 addr/s，Base58 链约 1.0e7，均取保守值
        if gpu_mode:
            default_rate = 9_000_000 if meta["is_evm"] else 7_000_000
        else:
            default_rate = 20000
        est = target / max(1, self.rate or default_rate)
        text = self.t("hint_diff", n=n, target=human_target(target), eta=fmt_duration(est))
        if len(rules) > 1:
            text += self.t("rules_active", n=len(rules))
        if est > 600:
            text += self.t("hint_slow")
        if not meta["is_evm"]:
            text += self.t("hint_case")
        if n > lic.FREE_LIMIT:
            text += self.t("credit_hint", free=lic.FREE_LIMIT)
        self.canvas.itemconfig(self.dyn["hint"], text=text,
                               fill=AMBER if est > 600 else MUTED)
        self._refresh_credit()

    # ---------- 鼠标

    def _in(self, x, y, rect):
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def _hit_button(self, px, py):
        x, y = px / SCALE, py / SCALE
        for btn in self.buttons:
            if self._in(x, y, btn["rect"]):
                return btn
        return None

    def _on_motion(self, event):
        target = self._hit_button(event.x, event.y)
        changed = False
        for btn in self.buttons:
            want = btn is target and btn["enabled"]
            if btn["hover"] != want:
                btn["hover"] = want
                self._redraw_button(btn)
                changed = True
        if changed:
            self.canvas.configure(cursor="hand2" if target and target["enabled"] else "")

    def _on_press(self, event):
        x, y = event.x / SCALE, event.y / SCALE

        # 1) 下拉是否展开，优先处理
        for dkey, d in self.dropdowns.items():
            if d["open"]:
                for i, rect in enumerate(d["option_rects"]):
                    if self._in(x, y, rect):
                        self._choose_option(dkey, i)
                        return
                self._close_dropdown(dkey)
                return

        # 2) 点击下拉标题区
        for dkey, d in self.dropdowns.items():
            if self._in(x, y, d["rect"]):
                if dkey == "chain" and self.running:
                    return
                self._open_dropdown(dkey)
                return

        # 3) 按钮
        for btn in self.buttons:
            if btn["enabled"] and self._in(x, y, btn["rect"]) and btn["cmd"]:
                btn["cmd"]()
                return

    def _on_release(self, _event):
        pass

    # ---------- 启停

    def _on_start(self):
        if self.running:
            return
        meta = self.meta()
        rules = self._effective_rules()

        # 多规则并行属于付费功能：未授权只能匹配 1 条
        if len(rules) > 1 and not self._multi_rules_allowed():
            self._ask_license()
            if not self._multi_rules_allowed():
                self.canvas.itemconfig(self.dyn["status"],
                                       text=self.t("rules_need_license"), fill=AMBER)
                return

        for r in rules:
            if any(ch not in meta["alphabet"] for ch in r["prefix"] + r["suffix"]):
                self.canvas.itemconfig(self.dyn["status"], text=self.t("status_error"), fill=RED)
                return
            if len(r["prefix"]) + len(r["suffix"]) > meta["maxlen"]:
                self.canvas.itemconfig(self.dyn["status"], text=self.t("status_error"), fill=RED)
                return

        # 多规则并行 GPU / CPU 都支持，内核里就是规则表逐条比对
        try:
            self.want = max(1, min(int(self._entry_value("count", raw=True) or "1"), 100000))
        except ValueError:
            self.want = 1

        # ---- 授权校验：取所有规则里最长的固定位数，> 免费上限时按条扣额度
        fixed = max([len(r["prefix"]) + len(r["suffix"]) for r in rules] or [0])
        need = lic.needed_count(fixed, self.want)
        if need > 0 and self.license.time_active():
            need = 0

        # ---- 开跑前先让用户确认：规则 / 模式 / 数量 / 扣多少额度
        if rules:
            shown = rules[:8]
            lines = [self.t("cf_rule_item", i=i + 1, pre=(r["prefix"] or "—"),
                            suf=(r["suffix"] or "—")) for i, r in enumerate(shown)]
            if len(rules) > len(shown):
                lines.append(self.t("cf_rule_more", n=len(rules)))
            rule_txt = "\n".join(lines)
        else:
            rule_txt = self.t("cf_rule_none")
        mode_txt = (self.t("cf_mode_gpu", gpu=self.gpu_info.get("name", "GPU"), n=self.threads)
                    if (self.use_gpu and self.gpu_info)
                    else self.t("cf_mode_cpu", n=self.threads))
        chain_txt = f"{CHAINS[self.chain]['tag']} · {CHAINS[self.chain]['name']}"

        if need > 0:
            have = self.license.remaining()
            if have >= need:
                credit_txt, credit_color = self.t("cf_credit_use", n=need, have=have,
                                                  left=have - need), GREEN
                warn, warn_color = self.t("cf_warn"), AMBER
            else:
                credit_txt, credit_color = self.t("cf_credit_short", n=need, have=have), RED
                warn, warn_color = self.t("cf_warn_short"), AMBER
        elif self.license.time_active():
            until = datetime.fromtimestamp(self.license.pure_time_until()).strftime("%Y-%m-%d")
            credit_txt, credit_color = self.t("credit_time", date=until), GREEN
            warn, warn_color = self.t("cf_warn_free"), DIM
        else:
            credit_txt, credit_color = self.t("cf_credit_free"), MUTED
            warn, warn_color = self.t("cf_warn_free"), DIM

        dlg = StartConfirmDialog(self.root, self.t, [
            (self.t("cf_rules"), rule_txt, CYAN),
            (self.t("cf_mode"), mode_txt, CYAN),
            (self.t("cf_chain"), chain_txt, CYAN),
            (self.t("cf_qty"), str(self.want), CYAN),
            (self.t("cf_credit"), credit_txt, credit_color),
        ], warn, warn_color, self.t("cf_ok"))
        if not dlg.ok:
            self._refresh_credit()
            return

        if need > 0:
            if self.license.remaining() < need:
                if not self._ask_license():
                    self._refresh_credit()
                    return
                if self.license.remaining() < need:
                    messagebox.showwarning(
                        self.t("license_title"),
                        self.t("need_credit", fixed=fixed, need=need, free=lic.FREE_LIMIT,
                               have=self.license.remaining()))
                    self._refresh_credit()
                    return
            if not self.license.reserve(need):
                messagebox.showwarning(
                    self.t("license_title"),
                    self.t("need_credit", fixed=fixed, need=need, free=lic.FREE_LIMIT,
                           have=self.license.remaining()))
                self._refresh_credit()
                return
        self.reserved = need
        self._refresh_credit()
        if need > 0:
            self._toast(self.t("credit_charged", n=need))

        self.running = True
        self.results = []
        self.latest = None
        self.collected = 0
        self.attempts = 0
        self.rate = 0
        self.elapsed = 0.0
        self.typewriter = 0
        self.full_addr = ""
        self.reveal = False
        self.blink = 0

        c = self.canvas
        c.itemconfig(self.dyn["attempts"], text="0", fill=TEXT)
        c.itemconfig(self.dyn["rate"], text="--", fill=TEXT)
        c.itemconfig(self.dyn["elapsed"], text="--", fill=TEXT)
        c.itemconfig(self.dyn["eta"], text="--", fill=TEXT)
        c.itemconfig(self.dyn["addr"], text=self.t("searching"), fill=DIM)
        c.itemconfig(self.dyn["key"], text=self.t("nothing"), fill=DIM)
        c.itemconfig(self.dyn["status"], text=self.t("status_init"), fill=CYAN)
        c.itemconfig(self.dyn["collected"], text=self.t("collected", a=0, b=self.want), fill=MUTED)
        c.coords(self.dyn["bar_fill"], S(48), S(BAR_Y1), S(48), S(BAR_Y2))
        c.itemconfig(self.dyn["bar_fill"], fill=CYAN)
        c.itemconfig(self.dyn["bar_glow"], state="normal")

        for b in (self.btn_start, self.btn_copy_addr, self.btn_reveal, self.btn_copy_key):
            self._set_enabled(b, False)
        self._set_enabled(self.btn_stop, True)

        if self.use_gpu and self.gpu_info:
            self.active = self.gpu_runner
        else:
            self.active = self.runner

        # 启动时快照规则，结果里的「规则」列按命中下标取文本
        self.rules_snapshot = list(rules)
        p0 = rules[0]["prefix"] if rules else ""
        s0 = rules[0]["suffix"] if rules else ""
        self.active.start(self.chain, p0, s0, self.threads, self.want,
                          rules=rules if len(rules) > 1 else None)

    def _on_stop(self):
        if not self.running:
            return
        self.runner.stop()
        self.gpu_runner.stop()
        self.running = False
        self._settle_credits()
        self.canvas.itemconfig(self.dyn["status"], text=self.t("status_abort"), fill=MUTED)
        self._set_enabled(self.btn_start, True)
        self._set_enabled(self.btn_stop, False)
        if self.results:
            self._enable_result_buttons()

    def _enable_result_buttons(self):
        self._set_enabled(self.btn_copy_addr, True)
        self._set_enabled(self.btn_reveal, True)
        self._set_enabled(self.btn_copy_key, True)

    # ---------- 授权

    def _current_fixed_chars(self):
        meta = self.meta()
        prefix = self._entry_value("prefix").strip()
        suffix = self._entry_value("suffix").strip()
        if meta["is_evm"]:
            prefix = prefix.replace("0x", "").replace("0X", "")
            suffix = suffix.replace("0x", "").replace("0X", "")
        return len(prefix) + len(suffix)

    def _refresh_mid(self):
        if "mid" not in self.dyn:
            return
        try:
            did = device_id()
        except Exception:
            did = "-"
        self.canvas.itemconfig(self.dyn["mid"], text=did)

    def _copy_mid(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(device_id())
        except Exception:
            return
        self._toast(self.t("mid_copied"))

    def _refresh_credit(self):
        if "credit" not in self.dyn:
            return
        self._refresh_mid()
        fixed = self._current_fixed_chars()
        if fixed <= lic.FREE_LIMIT:
            text, color = self.t("credit_free"), MUTED
        elif self.license.tampered:
            text, color = self.t("credit_tampered"), RED
        elif self.license.clock_rolled_back:
            text, color = self.t("credit_clock"), RED
        elif self.license.time_active():
            until = datetime.fromtimestamp(self.license.pure_time_until()).strftime("%Y-%m-%d")
            text, color = self.t("credit_time", date=until), GREEN
        elif self.license.both_until() > 0:
            until = datetime.fromtimestamp(self.license.both_until()).strftime("%m-%d")
            text, color = self.t("credit_both", date=until, n=self.license.remaining()), GREEN
        else:
            remain = self.license.remaining()
            text = self.t("credit", n=remain) if remain > 0 else self.t("credit_lock")
            color = GREEN if remain > 0 else AMBER
        self.canvas.itemconfig(self.dyn["credit"], text=text, fill=color)

    def _ask_license(self):
        before = self.license.remaining()
        dlg = LicenseDialog(self.root, self.t, self.license)
        self._refresh_credit()
        if not dlg.result:
            return False
        self._toast(self.t("license_ok_short", n=self.license.remaining() - before))
        return True
    def _toast(self, text, ms=2600):
        if "status" not in self.dyn:
            return
        self.canvas.itemconfig(self.dyn["status"], text=text, fill=GREEN)

        def restore():
            if "status" in self.dyn and not self.running:
                self.canvas.itemconfig(self.dyn["status"], text=self.t("status_idle"), fill=MUTED)

        self.root.after(ms, restore)

    def _on_license(self):
        self._ask_license()

    # ---------- 购买授权码

    def _buy_url(self):
        return f"{BUY_URL_BASE}?mid={device_id()}"

    def _qr_canvas(self, parent, text, px=236):
        """把二维码画成黑方块（纯 Canvas，不生成图片文件）"""
        canvas = tk.Canvas(parent, width=px, height=px, bg="#FFFFFF", bd=0,
                           highlightthickness=2, highlightbackground=CYAN_FAINT)
        try:
            matrix = qr_code.make_matrix(text)
        except Exception:
            return None, canvas
        n = len(matrix)
        quiet = 4                     # 静区，扫码器需要
        total = n + quiet * 2
        cell = max(1, px // total)
        off = (px - cell * total) // 2
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    x0 = off + (x + quiet) * cell
                    y0 = off + (y + quiet) * cell
                    canvas.create_rectangle(x0, y0, x0 + cell, y0 + cell,
                                            fill="#000000", width=0)
        return matrix, canvas

    def _on_buy(self):
        mid = device_id()
        url = self._buy_url()

        top = tk.Toplevel(self.root)
        top.title(self.t("buy_title"))
        top.configure(bg=BG)
        top.resizable(False, False)
        top.transient(self.root)
        top.grab_set()

        w, h = 800, 408
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2)
        y = self.root.winfo_rooty() + 120
        top.geometry(f"{w}x{h}+{x}+{y}")

        wrap = tk.Frame(top, bg=BG, highlightbackground=CYAN_FAINT, highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=10, pady=10)

        body = tk.Frame(wrap, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(12, 4))

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=BG)
        right.pack(side="right", padx=(14, 0))

        tk.Label(left, text=self.t("buy_note"), bg=BG, fg=MUTED, font=F_CN_SMALL,
                 anchor="w", justify="left", wraplength=486).pack(fill="x", pady=(0, 10))

        tk.Label(left, text=" // DEVICE ID ", bg=BG, fg=AMBER,
                 font=("Consolas", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(left, text=mid, bg=PANEL_FILL, fg=AMBER, font=("Consolas", 13, "bold"),
                 anchor="w", padx=10, pady=6).pack(fill="x", pady=(2, 10))

        tk.Label(left, text=" // URL ", bg=BG, fg=CYAN_DIM,
                 font=("Consolas", 10, "bold"), anchor="w").pack(fill="x")
        uvar = tk.StringVar(value=url)
        ent = tk.Entry(left, textvariable=uvar, bg=PANEL_FILL, fg=CYAN, relief="flat",
                       font=("Consolas", 10), highlightthickness=1,
                       highlightbackground=CYAN_FAINT, readonlybackground=PANEL_FILL)
        ent.configure(state="readonly")
        ent.pack(fill="x", ipady=5, pady=(2, 10))
        ent.select_range(0, "end")

        tk.Label(left, text=self.t("buy_hint"), bg=BG, fg=DIM, font=F_LABEL,
                 anchor="w").pack(fill="x")

        # 右侧：二维码（手机直接扫）
        tk.Label(right, text=self.t("buy_scan"), bg=BG, fg=CYAN,
                 font=("Consolas", 10, "bold")).pack(pady=(0, 6))
        _, qr_canvas = self._qr_canvas(right, url)
        qr_canvas.pack()
        if len(qr_canvas.find_all()) == 0:
            tk.Label(right, text="QR FAILED", bg="#FFFFFF", fg="#B00000",
                     font=F_LABEL, width=20, height=8).pack()

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(fill="x", padx=16, pady=(6, 12))

        def copy_link():
            top.clipboard_clear()
            top.clipboard_append(url)
            hint.configure(text=self.t("buy_copied"))

        def open_link():
            try:
                if hasattr(os, "startfile"):
                    os.startfile(url)      # 交给系统默认浏览器；本进程不发起任何网络请求
                else:
                    copy_link()
            except Exception:
                copy_link()

        tk.Button(foot, text=self.t("buy_copy"), command=copy_link, bg=BG, fg=CYAN,
                  activebackground=BG, activeforeground=CYAN, relief="flat",
                  font=F_BTN_SM, bd=0, highlightthickness=1, highlightbackground=CYAN_FAINT,
                  cursor="hand2", width=14).pack(side="left")
        tk.Button(foot, text=self.t("buy_open"), command=open_link, bg=CYAN_FAINT, fg=CYAN,
                  activebackground=CYAN_DIM, activeforeground="#FFFFFF", relief="flat",
                  font=F_BTN_SM, bd=0, highlightthickness=0, cursor="hand2",
                  width=16).pack(side="left", padx=(10, 0))
        tk.Button(foot, text=self.t("license_cancel"), command=top.destroy, bg=BG, fg=MUTED,
                  activebackground=BG, activeforeground=CYAN, relief="flat", font=F_BTN_SM,
                  bd=0, highlightthickness=0, cursor="hand2", width=8).pack(side="right")

        hint = tk.Label(foot, text="", bg=BG, fg=GREEN, font=F_LABEL, anchor="e")
        hint.pack(side="right", padx=(0, 12))

    def _settle_credits(self):
        """开跑即扣，不按结果退次（点开始生成就扣除，中止/失败都不退）"""
        self.reserved = 0
        self._refresh_credit()

    def _toggle_reveal(self):
        if not self.latest:
            return
        self.reveal = not self.reveal
        self.canvas.itemconfig(self.btn_reveal["ids"][1],
                               text=self.t("hide") if self.reveal else self.t("show"))
        self._render_key()

    def _render_key(self):
        if not self.latest:
            return
        priv = self.latest["priv"]
        if self.reveal:
            self.canvas.itemconfig(self.dyn["key"], text=priv, fill=AMBER)
        else:
            self.canvas.itemconfig(self.dyn["key"], text="·" * 44 + "  " + priv[-4:], fill=DIM)

    def _copy(self, text):
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.canvas.itemconfig(self.dyn["status"], text=self.t("status_copy"), fill=CYAN)

    def _copy_secret(self):
        if not self.latest:
            return
        self._copy(self.latest["priv"])
        self.canvas.itemconfig(self.dyn["status"], text=self.t("status_key_copy"), fill=AMBER)

    # ---------- 导出

    def _on_export(self):
        if not self.results:
            messagebox.showinfo(self.t("export"), self.t("export_empty"))
            return
        if not messagebox.askyesno(self.t("export_title"),
                                   self.t("export_confirm", n=len(self.results))):
            return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.t("export"),
            initialdir=ROOT_DIR,
            initialfile=default_filename(f"vanity_{self.chain}"),
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not path:
            return

        headers = [self.t("col_index"), self.t("col_chain"), self.t("col_addr"),
                   self.t("col_key"), self.t("col_attempts"), self.t("col_seconds"),
                   self.t("col_rule"), self.t("col_time")]
        rows = []
        for r in self.results:
            rows.append([r["index"], r["chain"], r["address"], r["priv"],
                         r["attempts"], r["elapsed"], r["rule"], r["time"]])
        try:
            write_xlsx(path, f"{self.chain.upper()} vanity", headers, rows,
                       [6, 10, 44, 70, 14, 12, 22, 22])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(self.t("export"), self.t("export_fail", err=str(exc)))
            return

        self.canvas.itemconfig(self.dyn["status"], text=self.t("status_export"), fill=GREEN)
        messagebox.showinfo(self.t("export"), self.t("export_done", n=len(rows), path=path))

    # ---------- 显示恢复

    def _restore_display(self):
        c = self.canvas
        if "attempts" not in self.dyn:
            return
        c.itemconfig(self.dyn["attempts"], text=fmt_int(self.attempts) if self.attempts else "--")
        c.itemconfig(self.dyn["rate"], text=f"{self.rate:,}" if self.rate else "--")
        c.itemconfig(self.dyn["elapsed"], text=fmt_duration(self.elapsed) if self.elapsed else "--")
        c.itemconfig(self.dyn["eta"], text=fmt_duration(self.eta) if self.eta else "--")
        c.itemconfig(self.dyn["collected"], text=self.t("collected", a=self.collected, b=self.want))
        self._apply_threads_display()

        if self.latest:
            self.full_addr = self.latest["address"]
            c.itemconfig(self.dyn["addr"], text=self.full_addr, fill=CYAN)
            self._render_key()
            self._enable_result_buttons()
        else:
            c.itemconfig(self.dyn["addr"], text=self.t("waiting"), fill=DIM)
            c.itemconfig(self.dyn["key"], text=self.t("nothing"), fill=DIM)

        if self.running:
            c.itemconfig(self.dyn["status"], text=self.t("status_run", n=self.threads), fill=CYAN)
            self._set_enabled(self.btn_start, False)
            self._set_enabled(self.btn_stop, True)
        else:
            c.itemconfig(self.dyn["status"], text=self.t("status_idle"), fill=MUTED)
            self._set_enabled(self.btn_start, True)
            self._set_enabled(self.btn_stop, False)
        self._refresh_credit()

        self._set_enabled(self.btn_export, bool(self.results))

    # ---------- 动画

    def _tick(self):
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self._animate()
        self.root.after(40, self._tick)

    def _animate(self):
        c = self.canvas
        self.phase += 1

        self.scan_y += 3
        if self.scan_y > DESIGN_H:
            self.scan_y = -10
        c.coords(self.dyn["scan"], S(0), S(self.scan_y), S(DESIGN_W), S(self.scan_y))

        if self.running:
            on = (math.sin(self.phase / 4) + 1) / 2 > 0.5
            c.itemconfig(self.dyn["led"], fill=CYAN if on else "#0E6A7C")
            self.flow_x += 14
            if self.flow_x > 884:
                self.flow_x = -40
            fx = 48 + self.flow_x
            c.coords(self.dyn["bar_glow"], S(max(48, fx)), S(BAR_Y1 + 1),
                     S(min(932, fx + 34)), S(BAR_Y2 - 1))
            c.itemconfig(self.dyn["bar_glow"], state="normal")
        else:
            breathe = (math.sin(self.phase / 9) + 1) / 2
            c.itemconfig(self.dyn["led"], fill="#1B6E80" if breathe > 0.4 else "#0C3C48")
            c.itemconfig(self.dyn["bar_glow"], state="hidden")

        if self.latest and not self.running:
            if self.typewriter < len(self.full_addr):
                self.typewriter += 2
                c.itemconfig(self.dyn["addr"], text=self.full_addr[:self.typewriter], fill=CYAN)
            else:
                self.blink += 1
                if self.blink < 8:
                    c.itemconfig(self.dyn["addr"],
                                 fill=CYAN if self.blink % 2 == 0 else GREEN)

    # ---------- 引擎事件

    def _handle(self, event):
        kind = event.get("t")
        c = self.canvas

        if kind == "ready":
            self.threads = event.get("threads", self.threads)
            gpu_name = event.get("gpu")
            if gpu_name:
                c.itemconfig(self.dyn["status"],
                             text=self.t("status_gpu", name=gpu_name.replace("NVIDIA GeForce ", "")),
                             fill=CYAN)
            else:
                c.itemconfig(self.dyn["status"],
                             text=self.t("status_run", n=self.threads), fill=CYAN)
            if "threads" in self.dyn:
                self._apply_threads_display()

        elif kind == "building":
            c.itemconfig(self.dyn["status"], text=self.t("status_building"), fill=AMBER)

        elif kind == "progress":
            self.attempts = event.get("attempts", 0)
            self.rate = event.get("rate", 0) or 0
            self.elapsed = event.get("elapsed", 0) or 0
            self.eta = event.get("eta")
            self.target = event.get("target", 1) or 1
            self.collected = event.get("collected", self.collected)
            self.want = event.get("count", self.want)

            c.itemconfig(self.dyn["attempts"], text=fmt_int(self.attempts))
            c.itemconfig(self.dyn["rate"], text=f"{self.rate:,}" if self.rate else "--")
            c.itemconfig(self.dyn["elapsed"], text=fmt_duration(self.elapsed))
            c.itemconfig(self.dyn["eta"], text=fmt_duration(self.eta))
            c.itemconfig(self.dyn["collected"], text=self.t("collected", a=self.collected, b=self.want))

            pct = min(1.0, self.attempts / (self.target * max(1, self.want))) if self.target else 0
            x = max(51.0, 48 + (932 - 48) * pct)
            c.coords(self.dyn["bar_fill"], S(48), S(BAR_Y1), S(x), S(BAR_Y2))

        elif kind == "found":
            item = {
                "index": event.get("index", len(self.results) + 1),
                "chain": self.meta()["tag"],
                "address": event.get("address", ""),
                "priv": event.get("privHex", ""),
                "attempts": event.get("attempts", 0),
                "elapsed": event.get("elapsed", 0),
                "rule": self._rule_text(event.get("ruleIndex", 0)),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.results.append(item)
            self.latest = item
            self.collected = len(self.results)
            self.reveal = False
            self.blink = 0
            self.typewriter = 0
            self.full_addr = item["address"]

            c.itemconfig(self.dyn["eta"], text="HIT", fill=GREEN)
            c.itemconfig(self.dyn["collected"],
                         text=self.t("collected", a=self.collected, b=self.want), fill=GREEN)
            self._render_key()
            self._enable_result_buttons()
            self._set_enabled(self.btn_export, True)

        elif kind == "done":
            self.running = False
            self.attempts = event.get("attempts", self.attempts)
            self.elapsed = event.get("elapsed", self.elapsed) or 0
            if self.elapsed > 0:
                self.rate = int(self.attempts / self.elapsed)
            self.eta = 0
            self._settle_credits()

            self._set_enabled(self.btn_start, True)
            self._set_enabled(self.btn_stop, False)
            c.itemconfig(self.dyn["status"], text=self.t("status_hit"), fill=GREEN)
            c.itemconfig(self.dyn["attempts"], text=fmt_int(self.attempts))
            c.itemconfig(self.dyn["rate"], text=f"{self.rate:,}")
            c.itemconfig(self.dyn["elapsed"], text=fmt_duration(self.elapsed))
            c.itemconfig(self.dyn["eta"], text="0s", fill=GREEN)
            c.coords(self.dyn["bar_fill"], S(48), S(BAR_Y1), S(932), S(BAR_Y2))
            c.itemconfig(self.dyn["bar_fill"], fill=GREEN)
            c.itemconfig(self.dyn["bar_glow"], state="hidden")

        elif kind == "error":
            msg = event.get("message", "")
            if msg == "@NODE_NOT_FOUND":
                msg = self.t("err_node")
            elif msg.startswith("@"):
                msg = self.t(msg[1:])
            self.running = False
            self._settle_credits()
            self._set_enabled(self.btn_start, True)
            self._set_enabled(self.btn_stop, False)
            c.itemconfig(self.dyn["status"], text=self.t("status_error"), fill=RED)
            c.itemconfig(self.dyn["addr"], text=msg, fill=RED)

        elif kind == "_exit":
            if self.running:
                self.running = False
                self._settle_credits()
                self._set_enabled(self.btn_start, True)
                self._set_enabled(self.btn_stop, False)
                c.itemconfig(self.dyn["status"], text=self.t("status_abort"), fill=MUTED)

    def _rule_text(self, index=0):
        """命中规则的可读文本；多规则时按启动快照取对应那条"""
        rules = self.rules_snapshot or self._effective_rules()
        rule = rules[index] if 0 <= index < len(rules) else None
        if rule is None:
            rule = {"prefix": self._entry_value("prefix").strip(),
                    "suffix": self._entry_value("suffix").strip()}
        parts = []
        if rule.get("prefix"):
            parts.append(f"{rule['prefix']}*")
        if rule.get("suffix"):
            parts.append(f"*{rule['suffix']}")
        return " ".join(parts) if parts else self.t("rule_random")


def main():
    global SCALE
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    try:
        SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except (tk.TclError, ZeroDivisionError):
        SCALE = 1.0

    app = HUDApp(root)

    def on_close():
        try:
            app._save_state()      # 关窗口前把规则/链/语言/线程/数量/GPU 记住
        except Exception:
            pass
        try:
            if app.running:
                app._on_stop()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()

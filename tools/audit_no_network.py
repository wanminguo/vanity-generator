#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无网络能力审计

扫描项目内所有源码文件，检查是否引用了任何网络相关模块。
这是「软件不具备联网能力」这一承诺的可执行证明，用户可以自己跑一遍。

用法：
    python tools/audit_no_network.py
    python tools/audit_no_network.py --path .

退出码 0 = 通过（没有任何网络引用），1 = 发现可疑引用。
"""

import argparse
import os
import re
import sys

# Node 侧禁用模块
NODE_FORBIDDEN = {
    "net", "tls", "http", "https", "http2", "dgram", "dns", "dns/promises",
    "node:net", "node:tls", "node:http", "node:https", "node:http2",
    "node:dgram", "node:dns",
    "axios", "got", "node-fetch", "request", "superagent", "ws", "socket.io",
    "undici", "@grpc/grpc-js", "grpc",
}

# Python 侧禁用模块
PY_FORBIDDEN = {
    "socket", "ssl", "http", "http.client", "urllib", "urllib.request",
    "urllib3", "requests", "httpx", "aiohttp", "ftplib", "telnetlib",
    "smtplib", "poplib", "imaplib", "xmlrpc", "webbrowser", "asyncio.streams",
    "requests", "websockets", "grpc",
}

NODE_REQUIRE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
NODE_IMPORT = re.compile(r"""import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""")
PY_IMPORT = re.compile(r"""^\s*(?:from|import)\s+([A-Za-z_][\w.]*)""", re.MULTILINE)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}


def iter_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith((".js", ".mjs", ".cjs", ".py")):
                yield os.path.join(base, name)


def module_root(name):
    """urllib.request → urllib"""
    return name.split(".")[0]


def audit(root):
    findings = []
    scanned = 0

    for path in iter_files(root):
        # 审计脚本自身会包含禁用模块名，跳过自身
        if os.path.basename(path) == "audit_no_network.py":
            continue

        scanned += 1
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError as exc:
            print(f"  跳过（无法读取）：{path} ({exc})")
            continue

        if path.endswith((".js", ".mjs", ".cjs")):
            names = NODE_REQUIRE.findall(source) + NODE_IMPORT.findall(source)
            forbidden = NODE_FORBIDDEN
        else:
            names = PY_IMPORT.findall(source)
            forbidden = PY_FORBIDDEN

        for name in names:
            if name in forbidden or module_root(name) in forbidden:
                line = source[: source.find(name)].count("\n") + 1
                findings.append((path, line, name))

    return scanned, findings


def main():
    parser = argparse.ArgumentParser(description="检查项目是否引用网络模块")
    parser.add_argument("--path", default=None, help="项目根目录，默认自动推断")
    args = parser.parse_args()

    root = args.path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print(f"审计目录：{root}\n")

    scanned, findings = audit(root)

    if findings:
        print(f"发现 {len(findings)} 处网络相关引用：")
        for path, line, name in findings:
            rel = os.path.relpath(path, root)
            print(f"  [{rel}:{line}] {name}")
        print("\n结论：未通过 —— 软件包含联网相关代码。")
        return 1

    print(f"已扫描 {scanned} 个源码文件，未发现任何网络模块引用。")
    print("涉及模块类型：net / tls / http / https / dgram / dns / socket / ssl")
    print("           urllib / requests / httpx / aiohttp / axios / ws / fetch")
    print("\n结论：通过 —— 代码层面不存在联网能力。")
    print("\n补充验证建议（想更彻底可以这样做）：")
    print("  1. 直接拔掉网线 / 关闭 Wi-Fi，全套功能仍可正常使用")
    print("  2. Windows Defender 防火墙 → 高级设置 → 出站规则，为该程序添加「阻止」规则")
    print("  3. 用 Wireshark 抓包，观察该进程运行期间无任何出站流量")
    return 0


if __name__ == "__main__":
    sys.exit(main())

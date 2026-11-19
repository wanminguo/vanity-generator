# -*- coding: utf-8 -*-
"""授权码粘贴容错测试：换行 / 空格 / 全角句号 / 带序号 / 只粘半段"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import license as lic  # noqa: E402

NODE = r"C:\Program Files\nodejs\node.exe"
ISSUER = os.path.join(ROOT, "tools", "issue_license.js")

ok, fail = [], []


def check(name, cond, extra=""):
    (ok if cond else fail).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"   [{extra}]" if extra else ""))


# 拿一个真码当样本
out = subprocess.run([NODE, ISSUER, "issue", "--n", "10", "--count", "1", "--json"],
                     capture_output=True, text=True, encoding="utf-8")
import json                                              # noqa: E402
CODE = json.loads(out.stdout.strip().splitlines()[-1])["codes"][0]
PAY, SIG = CODE.split(".")
print(f"样本码长度 {len(CODE)}（{len(PAY)} + 1 + {len(SIG)}）\n")

# 1 原码
check("原样导入", lic.verify_code(CODE)["n"] == 10)

# 2 换行 + 空格 + 制表符
messy = "  " + PAY[:40] + "\n" + PAY[40:] + "\t . \r\n" + SIG[:40] + "\n" + SIG[40:] + "  "
check("换行 / 空格 / 制表符", lic.verify_code(messy)["n"] == 10)

# 3 全角句号当分隔符
check("全角句号「．」", lic.verify_code(PAY + "．" + SIG)["n"] == 10)
check("中文句号「。」", lic.verify_code(PAY + "。" + SIG)["n"] == 10)

# 4 连序号一起复制
check("带序号前缀 0001", lic.verify_code("0001  " + CODE)["n"] == 10)
check("带引号包裹", lic.verify_code('"' + CODE + '"')["n"] == 10)

# 5 零宽字符 / BOM
check("零宽空格 + BOM", lic.verify_code("\ufeff" + PAY + "\u200b" + "." + SIG)["n"] == 10)

# 6 只粘前半段
try:
    lic.verify_code(PAY)
    check("只粘前半段被拒", False, "居然通过了")
except lic.LicenseError as exc:
    check("只粘前半段被拒", True)
    print(f"     提示：{exc}")
    check("提示里说明是前半段", "前半段" in str(exc), str(exc))
    check("提示里给出完整长度", str(lic.CODE_TYPICAL_LEN) in str(exc), str(exc))

# 7 有句点但签名段为空
try:
    lic.verify_code(PAY + ".")
    check("句点后为空被拒", False, "居然通过了")
except lic.LicenseError as exc:
    check("句点后为空被拒", True)
    print(f"     提示：{exc}")
    check("提示里说明签名段丢了", "签名段" in str(exc), str(exc))

# 8 签名被截断
try:
    lic.verify_code(PAY + "." + SIG[:30])
    check("签名截断被拒", False, "居然通过了")
except lic.LicenseError as exc:
    check("签名截断被拒", True, str(exc))

# 9 空
try:
    lic.verify_code("")
    check("空码被拒", False, "居然通过了")
except lic.LicenseError as exc:
    check("空码被拒", True, str(exc))

# 10 describe_code 的界面诊断状态
check("诊断：空", lic.describe_code("")[0] == "empty")
check("诊断：完整码 ok", lic.describe_code(CODE)[0] == "ok", lic.describe_code(CODE)[1])
check("诊断：只有半段 → half", lic.describe_code(PAY)[0] == "half", lic.describe_code(PAY)[1])
check("诊断：不像开头 → half 且给说明",
      lic.describe_code("MTIsIm1pZCI6I1ZHLUFFOTgi")[0] == "half",
      lic.describe_code("MTIsIm1pZCI6I1ZHLUFFOTgi")[1])
check("不像开头的提示会点明 eyJ",
      "eyJ" in lic.describe_code("MTIsIm1pZCI6I1ZHLUFFOTgi")[1])
check("诊断：签名截断 → half",
      lic.describe_code(PAY + "." + SIG[:30])[0] == "half",
      lic.describe_code(PAY + "." + SIG[:30])[1])
check("诊断：完全没点 → noseg", lic.describe_code("不是码的一段文字")[0] == "noseg",
      lic.describe_code("不是码的一段文字")[1])

print(f"\n{len(ok)} PASS / {len(fail)} FAIL")
sys.exit(0 if not fail else 1)

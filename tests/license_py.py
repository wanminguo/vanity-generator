#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
授权体系测试：Node 签发 → Python 验签（跨语言互通），以及账本扣减/退款/防篡改。

运行：C:\\Python314\\python.exe tests\\license_py.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

import license as lic  # noqa: E402


def find_node():
    for p in (r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"):
        if os.path.isfile(p):
            return p
    return shutil.which("node")


NODE = find_node()
ISSUER = os.path.join(ROOT, "tools", "issue_license.js")

fail = 0


def check(name, cond, detail=""):
    global fail
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail != "" else ""))
    if not cond:
        fail += 1


def issue(n=10, extra=None):
    cmd = [NODE, ISSUER, "issue", "--n", str(n)]
    if extra:
        cmd += extra
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    codes = [ln.strip() for ln in out.stdout.splitlines() if "." in ln and not ln.startswith("签发")]
    return codes[-1]


def issue_time(days=30, exp=None):
    cmd = [NODE, ISSUER, "issue", "--days", str(days)]
    if exp is not None:
        cmd += ["--exp", str(exp)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    codes = [ln.strip() for ln in out.stdout.splitlines() if "." in ln and not ln.startswith("签发")]
    return codes[-1]


def issue_both(n=8, days=30):
    cmd = [NODE, ISSUER, "issue", "--n", str(n), "--days", str(days)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    codes = [ln.strip() for ln in out.stdout.splitlines() if "." in ln and not ln.startswith("签发")]
    return codes[-1]


def issue_mid(n=10, mid=None, days=None):
    if days:
        cmd = [NODE, ISSUER, "issue", "--n", str(n), "--days", str(days), "--mid", mid]
    else:
        cmd = [NODE, ISSUER, "issue", "--n", str(n), "--mid", mid]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    codes = [ln.strip() for ln in out.stdout.splitlines() if "." in ln and not ln.startswith("签发")]
    return codes[-1]


print("[1] 公钥与签发")
check("公钥已加载", lic.PUBLIC_KEY is not None, lic.PUBLIC_KEY_HEX[:16] + "...")

code = issue(10)
check("签发出一个码", len(code) > 40, code[:36] + "...")

payload = lic.verify_code(code)
check("Python 验签通过（Node 签的）", payload["type"] == "count", json.dumps(payload))
check("次数解析正确", payload["n"] == 10, payload["n"])
check("带唯一 ID", bool(payload.get("id")), payload.get("id"))

print("[2] 篡改与伪造")
bad_payload, bad_sig = code.split(".", 1)
tampered = bad_payload[:-2] + ("AA" if bad_payload[-2:] != "AA" else "BB") + "." + bad_sig
try:
    lic.verify_code(tampered)
    check("篡改 payload 应被拒绝", False, "居然通过了")
except lic.LicenseError as exc:
    check("篡改 payload 应被拒绝", True, str(exc)[:40])

tampered_sig = bad_payload + "." + bad_sig[:-2] + ("AA" if bad_sig[-2:] != "AA" else "BB")
try:
    lic.verify_code(tampered_sig)
    check("篡改签名应被拒绝", False, "居然通过了")
except lic.LicenseError as exc:
    check("篡改签名应被拒绝", True, str(exc)[:40])

code_b = issue(10)
try:
    lic.verify_code(code_b.replace(".", "", 1))
    check("去掉分隔符应被拒绝", False)
except lic.LicenseError:
    check("去掉分隔符应被拒绝", True)

print("[3] 免费额度边界")
check("7 位免费", lic.needed_count(7, 5) == 0, lic.needed_count(7, 5))
check("3 位免费", lic.needed_count(3, 50) == 0, lic.needed_count(3, 50))
check("8 位按条扣", lic.needed_count(8, 5) == 5, lic.needed_count(8, 5))
check("前缀3+后缀5=8 位按条扣", lic.needed_count(8, 1) == 1)

print("[4] 账本")
tmpdir = tempfile.mkdtemp(prefix="vanity_ledger_")
try:
    path = os.path.join(tmpdir, "ledger.json")
    ledger = lic.Ledger(path)
    check("初始额度 0", ledger.remaining() == 0, ledger.remaining())

    ledger.add_code(code)
    check("导入后额度 10", ledger.remaining() == 10, ledger.remaining())

    try:
        ledger.add_code(code)
        check("同码重复导入应拒绝", False)
    except lic.LicenseError as exc:
        check("同码重复导入应拒绝", True, str(exc)[:40])

    check("预留 3 次成功", ledger.reserve(3) is True)
    check("扣减后剩 7", ledger.remaining() == 7, ledger.remaining())

    ledger.refund(1)
    check("退款 1 次后剩 8", ledger.remaining() == 8, ledger.remaining())

    check("超额预留被拒绝", ledger.reserve(20) is False)
    check("超额失败后额度不变", ledger.remaining() == 8, ledger.remaining())

    ledger.reserve(8)
    check("用尽后剩 0", ledger.remaining() == 0, ledger.remaining())

    reloaded = lic.Ledger(path)
    check("重新加载额度保持", reloaded.remaining() == 0, reloaded.remaining())

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["credits"][0]["n"] = 999
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)

    hacked = lic.Ledger(path)
    check("手改账本被识别为篡改", hacked.tampered is True)
    check("手改后额度归零", hacked.remaining() == 0, hacked.remaining())
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

print("[5] 时长码")
code_time = issue_time(30)
payload_t = lic.verify_code(code_time)
check("时长码类型为 time", payload_t["type"] == "time", payload_t["type"])
check("带到期时间", payload_t["exp"] > int(time.time()), payload_t["exp"])

try:
    lic.verify_code(issue_time(30, exp=1000000000))
    check("过期时长码应被拒绝", False)
except lic.LicenseError as exc:
    check("过期时长码应被拒绝", True, str(exc)[:30])

tmp2 = tempfile.mkdtemp(prefix="vanity_time_")
try:
    p2 = os.path.join(tmp2, "ledger.json")
    ledger2 = lic.Ledger(p2)
    ledger2.add_code(code_time)
    check("时长码导入后生效", ledger2.time_active() is True)
    check("时长码不增加按次额度", ledger2.remaining() == 0, ledger2.remaining())
    check("到期时间可读", ledger2.time_until() == payload_t["exp"], ledger2.time_until())

    # 模拟系统时间被回拨：把 last_seen 推到未来
    ledger2.last_seen = int(time.time()) + 86400 * 3
    ledger2.save()
    rolled = lic.Ledger(p2)
    check("识别系统时间回拨", rolled.clock_rolled_back is True)
    check("回拨后时长码失效", rolled.time_active() is False)
    check("回拨后按次额度不受影响", rolled.remaining() == 0)
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

print("[6] 多位置冗余")
tmp3 = tempfile.mkdtemp(prefix="vanity_multi_")
try:
    code_m = issue(10)
    a = os.path.join(tmp3, "a.json")
    b = os.path.join(tmp3, "b.json")
    multi = lic.Ledger(a, mirrors=[b])
    multi.add_code(code_m)
    multi.reserve(4)
    check("主副本都存在", os.path.exists(a) and os.path.exists(b), f"{os.path.exists(a)}/{os.path.exists(b)}")
    check("扣减后剩 6", multi.remaining() == 6, multi.remaining())

    os.remove(a)
    after_delete = lic.Ledger(a, mirrors=[b])
    check("删掉主存储后额度仍为 6", after_delete.remaining() == 6, after_delete.remaining())
    check("删掉主存储不算篡改", after_delete.tampered is False)

    os.remove(b)
    empty = lic.Ledger(a, mirrors=[b])
    check("两处都删才归零", empty.remaining() == 0, empty.remaining())
finally:
    shutil.rmtree(tmp3, ignore_errors=True)

print("[7] 限次 + 限期码（次数与时间共存）")
code_both = issue_both(8, 30)
payload_b = lic.verify_code(code_both)
check("类型为 both", payload_b["type"] == "both", payload_b["type"])
check("带次数上限", payload_b["n"] == 8, payload_b.get("n"))
check("带到期时间", payload_b["exp"] > int(time.time()), payload_b.get("exp"))

tmp4 = tempfile.mkdtemp(prefix="vanity_both_")
try:
    p4 = os.path.join(tmp4, "ledger.json")
    led = lic.Ledger(p4)
    led.add_code(code_both)
    check("导入后可用 8 次", led.remaining() == 8, led.remaining())
    check("不算纯时长码（仍需扣次）", led.time_active() is False)
    check("限次码处于有效期内", led.both_until() > 0, led.both_until())
    check("预留 3 次", led.reserve(3) is True)
    check("扣减后剩 5", led.remaining() == 5, led.remaining())

    led.credits[0]["exp"] = int(time.time()) - 10
    led.save()
    expired = lic.Ledger(p4)
    check("到期后次数作废", expired.remaining() == 0, expired.remaining())
    check("到期后不再算有效码", expired.both_until() == 0, expired.both_until())
finally:
    shutil.rmtree(tmp4, ignore_errors=True)

print("[8] 设备绑定")
import device_id as dev  # noqa: E402
_current = dev.device_id()
check("设备 ID 格式正确", _current.startswith("VG-") and len(_current) == 22, _current)
check("两次调用结果一致", dev.device_id() == _current)

code_bound = issue_mid(10, _current)
p_bound = lic.verify_code(code_bound)
check("本机的绑定码可验签", p_bound.get("mid") == _current, p_bound.get("mid"))

code_foreign = issue_mid(10, "VG-0000-1111-2222-3333")
try:
    lic.verify_code(code_foreign)
    check("别的设备的绑定码被拒", False)
except lic.LicenseError as exc:
    check("别的设备的绑定码被拒", "签给" in str(exc), str(exc)[:46])

check("未绑定的码不受影响", lic.verify_code(issue(10)).get("mid") is None)
check("签发台可跳过绑定检查",
      lic.verify_code(code_foreign, skip_mid=True).get("mid") == "VG-0000-1111-2222-3333")

bound_mid = issue_mid(5, _current, days=30)
p_mid = lic.verify_code(bound_mid)
check("绑定 + 期限可以叠用", p_mid["type"] == "both" and p_mid["mid"] == _current,
      f"{p_mid['type']}/{p_mid.get('mid')}")

print("\n结果：" + ("全部通过" if fail == 0 else f"{fail} 项失败"))
sys.exit(0 if fail == 0 else 1)

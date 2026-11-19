#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
授权码与本地状态存储。

两种码（共用同一套 Ed25519 验签）：
  count  按次码  {"type":"count","n":10,"id":"唯一ID","iat":..}
         —— 次数记在本地，删掉本地记录可恢复。这是「离线 + 按次」的固有边界。
  time   时长码  {"type":"time","exp":到期时间戳,"id":"唯一ID","iat":..}
         —— 只认时间不认次数，删掉本地记录也没用；唯一缺口是改系统时间，
            用 last_seen 记录检测倒退。适合月卡 / 年卡。

免费边界：固定字符数（前缀 + 后缀）≤ 7 免费；> 7 位需要按次额度或生效中的时长码。

本地状态存三份（AppData / 系统缓存目录 / 注册表），读取时按 id 取「已用次数最多」的那份，
删掉其中一处不会让次数恢复。三处全删仍可恢复 —— 本地软件无法杜绝，见 README。
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time

from ed25519 import public_key_from_hex, verify

FREE_LIMIT = 7                  # 固定 7 位以内免费；8 位起每条扣 1 次
CLOCK_TOLERANCE = 3600          # 允许的时间漂移（秒），超出视为系统时间被回拨
APP_DIR_NAME = "VanityGen"

# 一个完整授权码的典型长度：payload 86 字符 + 点 + 签名 86 字符（绑定设备的更长）
CODE_TYPICAL_LEN = 173

# 码首的可见编号：A00001 / Z99999（26 组 × 99999，约 260 万个）
SN_RE = re.compile(r"^([A-Za-z]\d{5})-(eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]{20,})$")
SN_ANY_RE = re.compile(r"(?:[A-Za-z]\d{5}-)?eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]{20,}")

# 只防普通用户改 JSON；防不住专业逆向，项目定位里已接受这个边界
# 注意：这个密钥一旦发布就不能再改，否则所有已有账本都会被判为篡改而清零。
# 账本格式的版本信息走 payload 里的 "v" 字段，不要动这里。
_LEDGER_HMAC_KEY = b"vanity-generator-ledger-v1-2026"

REGISTRY_KEY_PATH = r"Software\VanityGen"
REGISTRY_VALUE_NAME = "LedgerState"
_REGISTRY_TOKEN = "@registry@"

try:
    from _public_key import PUBLIC_KEY_HEX  # noqa: F401
except ImportError:
    PUBLIC_KEY_HEX = ""

PUBLIC_KEY = public_key_from_hex(PUBLIC_KEY_HEX) if PUBLIC_KEY_HEX else None


class LicenseError(Exception):
    pass


# ---------------------------------------------------------------- 码解析 / 验签

def _b64d(text):
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError(f"授权码不是合法的 base64：{exc}") from exc


def clean_code_text(code):
    """把粘贴进来的授权码洗干净

    容忍：换行、空格、制表符、零宽字符 / BOM / 全角空格、
          中文句号「。」、全角句点「．」被当成分隔符、
          从聊天记录里连序号一起复制（自动抓出里面最长的一个「段.段」）。
    """
    text = str(code or "")
    for ch in ("\r", "\n", "\t", "\u00a0", "\u3000", "\u200b", "\u200c",
               "\u200d", "\ufeff", " "):
        text = text.replace(ch, "")
    for ch in ("．", "。", "·", "・", "…"):
        text = text.replace(ch, ".")
    text = text.strip()
    # 复制时带上了序号 / 引号 / 说明文字：抓出来真正的码
    # 我们的 payload 是 JSON 的 base64url，一定以 eyJ 开头，用它当锚点最稳
    # 码首可能带 6 位编号（A00001-），一并保留
    hits = SN_ANY_RE.findall(text)
    if hits:
        return max(hits, key=len)
    if "." not in text:
        seg = re.search(r"[A-Za-z0-9_-]{40,}", text)
        if seg:
            return seg.group(0)
    return text


def split_sn(text):
    """把码拆成 (编号, 码身)；没有编号时返回 ("", 原串)"""
    m = SN_RE.match(text or "")
    if m:
        return m.group(1).upper(), m.group(2)
    return "", (text or "")


def describe_code(code):
    """给界面用的即时诊断，返回 (状态, 说明文案)

    状态：empty / noseg / half / badsig / ok
    """
    text = clean_code_text(code)
    if not text:
        return "empty", "还没粘贴授权码"
    sn, core = split_sn(text)
    tag = f"编号 {sn} · " if sn else ""
    if "." not in core:
        if re.fullmatch(r"[A-Za-z0-9_-]+", core):
            if core.startswith("eyJ"):
                return "half", (tag + f"只有前半段（{len(core)} 字符）· 整码约 "
                                f"{CODE_TYPICAL_LEN} 字符（绑定设备的更长），"
                                f"中间差一个英文句点「.」和后面的签名段")
            return "half", (f"这段不像授权码的开头（{len(core)} 字符）：完整码是"
                            f"「可选的 6 位编号 +「-」」+「eyJ 开头的内容段」+「.」+「86 字符签名段」，"
                            f"共约 {CODE_TYPICAL_LEN} 字符；多半是复制时漏掉了开头和结尾")
        return "noseg", '缺少分隔符「.」，整码形如 xxxxx.yyyyy'
    head, _, tail = core.partition(".")
    if not head:
        return "noseg", "句点前面是空的"
    if not tail:
        return "half", tag + f"句点后面没有签名段（前半段 {len(head)} 字符）"
    if len(tail) < 80:
        return "half", tag + (f"签名段只有 {len(tail)} 字符（正常 86 字符 = 64 字节），"
                              f"后半段可能被截断了")
    return "ok", tag + f"结构正常：内容 {len(head)} + 签名 {len(tail)} 字符"


def parse_code(code):
    text = clean_code_text(code)
    _, core = split_sn(text)
    dot = core.rfind(".")
    if dot <= 0:
        if not core:
            raise LicenseError("授权码是空的，先粘贴完整的一行")
        if re.fullmatch(r"[A-Za-z0-9_-]+", core):
            if core.startswith("eyJ"):
                raise LicenseError(
                    f"这是授权码的前半段（{len(core)} 字符），后面还差一个英文句点「.」"
                    f"和签名段；完整码约 {CODE_TYPICAL_LEN} 字符（绑定设备的更长），请重新复制整行")
            raise LicenseError(
                f"这段不是授权码的开头（{len(core)} 字符）：完整码以 eyJ 开头的内容段起头，"
                f"中间一个英文句点「.」，再接 86 字符签名段，共约 {CODE_TYPICAL_LEN} 字符。"
                f"请回签发台点某一行复制，或打开导出的 TXT 整行复制")
        raise LicenseError('授权码格式错误：缺少分隔符 "."')
    head, tail = core[:dot], core[dot + 1:]
    if not tail:
        raise LicenseError(f"句点后面是空的：只有前半段（{len(head)} 字符），签名段没复制到")
    return _b64d(head), _b64d(tail)


def verify_code(code, current_mid=None, skip_mid=False):
    if PUBLIC_KEY is None:
        raise LicenseError("软件内没有公钥，请先运行 tools/issue_license.js init")

    payload_bytes, signature = parse_code(code)
    if len(signature) != 64:
        raise LicenseError(f"签名长度应为 64 字节，实际 {len(signature)}")
    if not verify(signature, payload_bytes, PUBLIC_KEY):
        raise LicenseError("授权码签名校验失败（码被改动过，或不是本软件签发的）")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError(f"授权码内容无法解析：{exc}") from exc

    if not payload.get("id"):
        raise LicenseError("授权码缺少唯一 ID")

    # 码首编号 vs 签名里的编号：不一致说明码首被改过，直接拒
    sn, _ = split_sn(clean_code_text(code))
    inner_sn = payload.get("sn")
    if sn and inner_sn and str(inner_sn).strip().upper() != sn:
        raise LicenseError(f"码首编号 {sn} 与签名里的编号 {inner_sn} 不一致（码被改过）")

    bound = payload.get("mid")
    if bound and not skip_mid:
        if current_mid is None:
            try:
                from device_id import device_id as _did
                current_mid = _did()
            except Exception:
                current_mid = ""
        if not current_mid:
            raise LicenseError("这个授权码绑定了设备，但读不到本机设备标识")
        if str(bound).strip().upper() != str(current_mid).strip().upper():
            raise LicenseError(
                f"授权码是签给 {bound} 的，本机设备 ID 是 {current_mid}，不能混用")

    exp = payload.get("exp")
    if exp is not None:
        try:
            exp = int(exp)
        except (TypeError, ValueError):
            raise LicenseError("授权码到期时间不合法")
        if exp < int(time.time()):
            raise LicenseError("授权码已过期")

    kind = payload.get("type")
    if kind == "count":
        n = payload.get("n")
        if not isinstance(n, int) or n <= 0:
            raise LicenseError("按次码的可用次数不合法")
    elif kind == "time":
        if exp is None:
            raise LicenseError("时长码缺少到期时间")
    elif kind == "both":
        n = payload.get("n")
        if not isinstance(n, int) or n <= 0:
            raise LicenseError("限次+限期码的可用次数不合法")
        if exp is None:
            raise LicenseError("限次+限期码缺少到期时间")
    else:
        raise LicenseError(f"不支持的授权类型：{kind}")

    return payload


def needed_count(fixed_chars, count):
    """超过免费额度时需要消耗的按次次数"""
    return count if fixed_chars > FREE_LIMIT else 0


# ---------------------------------------------------------------- 存储位置

def default_store_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME, "ledger.json")


def mirror_store_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME, ".state")


def default_stores():
    return [default_store_path(), mirror_store_path(), _REGISTRY_TOKEN]


# ---------------------------------------------------------------- 账本

class Ledger:
    def __init__(self, path=None, mirrors=None):
        """
        path=None 时使用默认三处存储（文件 ×2 + 注册表）；
        显式传入 path 时只用给出的路径（测试用）。
        """
        if path is not None:
            self.stores = [path] + list(mirrors or [])
        else:
            self.stores = default_stores()

        self.credits = []
        self.last_seen = 0
        self.tampered = False
        self.clock_rolled_back = False
        self._load()

    # ---------- 底层读写

    def _read_store(self, store):
        if store == _REGISTRY_TOKEN:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH) as key:
                    value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
                    return value if isinstance(value, str) else None
            except (ImportError, OSError, ValueError):
                return None
        try:
            with open(store, "r", encoding="utf-8") as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError):
            return None

    def _write_store(self, store, text):
        if store == _REGISTRY_TOKEN:
            try:
                import winreg
                key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH,
                                         0, winreg.KEY_SET_VALUE)
                try:
                    winreg.SetValueEx(key, REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, text)
                finally:
                    winreg.CloseKey(key)
                return True
            except (ImportError, OSError):
                return False
        try:
            folder = os.path.dirname(store)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = store + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, store)
            return True
        except OSError:
            return False

    # ---------- 签名

    @staticmethod
    def _sign_v2(credits, last_seen):
        raw = json.dumps({"credits": credits, "last_seen": last_seen},
                         ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hmac.new(_LEDGER_HMAC_KEY, raw, hashlib.sha256).hexdigest()

    @staticmethod
    def _sign_v1(credits):
        raw = json.dumps(credits, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hmac.new(_LEDGER_HMAC_KEY, raw, hashlib.sha256).hexdigest()

    def _validate(self, data):
        """返回 (credits, last_seen, 是否有效)"""
        if not isinstance(data, dict):
            return [], 0, False
        credits = data.get("credits")
        sig = data.get("sig")
        if not isinstance(credits, list) or not isinstance(sig, str):
            return [], 0, False

        last_seen = data.get("last_seen", 0)
        try:
            last_seen = int(last_seen)
        except (TypeError, ValueError):
            last_seen = 0

        if hmac.compare_digest(self._sign_v2(credits, last_seen), sig):
            return credits, last_seen, True
        if hmac.compare_digest(self._sign_v1(credits), sig):     # 兼容旧版单文件账本
            return credits, 0, True
        return [], 0, False

    # ---------- 载入与合并

    def _load(self):
        self.credits = []
        self.last_seen = 0
        self.tampered = False
        self.clock_rolled_back = False

        found_any = False
        valid_any = False
        merged = {}

        for store in self.stores:
            raw = self._read_store(store)
            if raw is None:
                continue
            found_any = True
            try:
                data = json.loads(raw)
            except ValueError:
                continue

            credits, last_seen, ok = self._validate(data)
            if not ok:
                continue
            valid_any = True
            self.last_seen = max(self.last_seen, last_seen)

            for item in credits:
                if not isinstance(item, dict):
                    continue
                cid = item.get("id")
                if not cid:
                    continue
                kind = item.get("type") or "count"
                entry = merged.get(cid)
                if entry is None:
                    merged[cid] = dict(item, type=kind)
                elif kind in ("count", "both"):
                    # 同一份记录在多处时，取「用得最多」的那个（宁可少给，不能多给）
                    entry["used"] = max(int(entry.get("used", 0) or 0),
                                        int(item.get("used", 0) or 0))

        self.credits = list(merged.values())

        if found_any and not valid_any:
            self.tampered = True
            self.credits = []

        now = int(time.time())
        if self.last_seen and now < self.last_seen - CLOCK_TOLERANCE:
            self.clock_rolled_back = True

    def save(self):
        now = int(time.time())
        if now > self.last_seen:
            self.last_seen = now

        payload = {
            "v": 2,
            "credits": self.credits,
            "last_seen": self.last_seen,
            "sig": self._sign_v2(self.credits, self.last_seen),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=1)

        written = False
        for store in self.stores:
            if self._write_store(store, text):
                written = True
        return written

    # ---------- 额度

    def remaining(self, now=None):
        """当前可用次数：按次码 + 限次码（限次码过期后不再计入）"""
        now = int(now if now is not None else time.time())
        total = 0
        for c in self.credits:
            kind = c.get("type") or "count"
            if kind not in ("count", "both"):
                continue
            if kind == "both" and int(c.get("exp", 0) or 0) <= now:
                continue
            try:
                total += max(0, int(c.get("n", 0)) - int(c.get("used", 0)))
            except (TypeError, ValueError):
                continue
        return total

    def licensed(self, now=None):
        """是否持有有效授权：有可用次数，或有生效中的时长 / 限次码

        多规则并行属于付费功能，只有这个方法返回 True 才能添加第 2 条及以后的规则。
        """
        now = int(now if now is not None else time.time())
        if self.tampered or self.clock_rolled_back:
            return False
        if self.remaining(now) > 0:
            return True
        try:
            return int(self.time_until() or 0) > now
        except (TypeError, ValueError):
            return False

    def time_until(self):
        """最晚的到期时刻（时长码与限次码都算），没有则 0"""
        best = 0
        for c in self.credits:
            kind = c.get("type") or "count"
            if kind not in ("time", "both"):
                continue
            try:
                best = max(best, int(c.get("exp", 0) or 0))
            except (TypeError, ValueError):
                continue
        return best

    def pure_time_until(self, now=None):
        """只在「纯时长码」里找最晚到期时刻（这类码不扣次数）"""
        now = int(now if now is not None else time.time())
        best = 0
        for c in self.credits:
            if (c.get("type") or "count") != "time":
                continue
            try:
                exp = int(c.get("exp", 0) or 0)
            except (TypeError, ValueError):
                continue
            if exp > now:
                best = max(best, exp)
        return best

    def time_active(self, now=None):
        """是否有生效中的纯时长码（不扣次数）。检测到时间回拨时一律不认"""
        if self.clock_rolled_back:
            return False
        return self.pure_time_until(now) > 0

    def both_until(self, now=None):
        """生效中的限次码的最晚到期时刻，没有则 0"""
        now = int(now if now is not None else time.time())
        if self.clock_rolled_back:
            return 0
        best = 0
        for c in self.credits:
            if (c.get("type") or "count") != "both":
                continue
            try:
                exp = int(c.get("exp", 0) or 0)
            except (TypeError, ValueError):
                continue
            if exp > now:
                best = max(best, exp)
        return best

    def add_code(self, code):
        payload = verify_code(code)
        cid = payload["id"]
        if any(c.get("id") == cid for c in self.credits):
            raise LicenseError("这个授权码已经导入过了，不能重复使用")

        kind = payload["type"]
        sn = payload.get("sn") or ""
        if kind == "count":
            self.credits.append({
                "type": "count",
                "id": cid,
                "sn": sn,
                "n": int(payload["n"]),
                "used": 0,
                "iat": int(payload.get("iat", int(time.time()) )),
            })
        elif kind == "time":
            self.credits.append({
                "type": "time",
                "id": cid,
                "sn": sn,
                "exp": int(payload["exp"]),
                "iat": int(payload.get("iat", int(time.time()))),
            })
        else:
            self.credits.append({
                "type": "both",
                "id": cid,
                "sn": sn,
                "n": int(payload["n"]),
                "used": 0,
                "exp": int(payload["exp"]),
                "iat": int(payload.get("iat", int(time.time()))),
            })

        self.tampered = False
        self.save()
        return payload

    def reserve(self, n):
        """预留 n 次；不足返回 False 且不做任何扣减"""
        if n <= 0:
            return True
        if self.remaining() < n:
            return False

        now = int(time.time())
        need = n
        for c in self.credits:
            kind = c.get("type") or "count"
            if kind not in ("count", "both"):
                continue
            if kind == "both" and int(c.get("exp", 0) or 0) <= now:
                continue
            avail = int(c.get("n", 0)) - int(c.get("used", 0))
            if avail <= 0:
                continue
            take = min(avail, need)
            c["used"] = int(c.get("used", 0)) + take
            need -= take
            if need == 0:
                break
        self.save()
        return True

    def refund(self, n):
        """退回没用掉的预留次数：先退回仍然生效的，再退其余的"""
        if n <= 0:
            return
        left = n
        now = int(time.time())

        for only_valid in (True, False):
            for c in reversed(self.credits):
                if left <= 0:
                    break
                kind = c.get("type") or "count"
                if kind not in ("count", "both"):
                    continue
                if only_valid and kind == "both" and int(c.get("exp", 0) or 0) <= now:
                    continue
                used = int(c.get("used", 0))
                if used <= 0:
                    continue
                give = min(used, left)
                c["used"] = used - give
                left -= give
            if left <= 0:
                break

        self.save()

    def used_ids(self):
        return {c.get("id") for c in self.credits if c.get("id")}

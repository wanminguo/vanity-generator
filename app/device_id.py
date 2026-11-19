# -*- coding: utf-8 -*-
"""
设备指纹（设备 ID）

用于把授权码绑定到一台机器。取值来源全部是 Windows 本机标识，不联网、不读任何
个人文件：

  1. HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid
     安装 Windows 时生成，重装系统会变，同一台机器的所有用户共用
  2. 系统盘卷序列号（GetVolumeInformationW）
     格式化硬盘会变

两者拼起来做 SHA-256，取前 16 位 hex 格式化成 VG-XXXX-XXXX-XXXX-XXXX。

稳定性说明（必须如实告知用户）：
  - 日常使用不会变；重装系统、换主板/硬盘会变，需要重新签发
  - 不是「绝对不可伪造」：管理员改注册表、虚拟机克隆都能造出同一个 ID
    这个功能的目标是防「一个码发给十个人各用一遍」，不是防专业逆向
"""

import hashlib
import os

_CACHE = None


def _machine_guid():
    try:
        import winreg
        # 显式指定 64 位视图，避免 32/64 位进程读到不同分支
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except Exception:
        return ""


def _volume_serial(drive="C:\\"):
    try:
        import ctypes
        vol = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive), None, 0,
            ctypes.byref(vol), None, None, None, 0)
        if ok:
            return f"{vol.value:08X}"
    except Exception:
        pass
    return ""


def device_id():
    """返回形如 VG-8F2A-19C4-7DE0-B3A1 的设备标识，进程内缓存"""
    global _CACHE
    if _CACHE:
        return _CACHE

    parts = []
    guid = _machine_guid()
    if guid:
        parts.append("guid:" + guid.lower())
    vol = _volume_serial()
    if vol:
        parts.append("vol:" + vol)

    if not parts:
        # 兜底：机器名 + 用户名（这两个用户自己就能改，只在不支持的平台上用）
        parts.append("host:" + os.environ.get("COMPUTERNAME", "").lower())
        parts.append("user:" + os.environ.get("USERNAME", "").lower())

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest().upper()
    _CACHE = "VG-" + "-".join(digest[i:i + 4] for i in range(0, 16, 4))
    return _CACHE


if __name__ == "__main__":
    did = device_id()
    print(did)
    print("machine guid:", _machine_guid() or "(读不到，已退化)")
    print("volume serial:", _volume_serial() or "(读不到)")

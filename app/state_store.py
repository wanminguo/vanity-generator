# -*- coding: utf-8 -*-
"""本地状态持久化：匹配规则、链、语言、线程、数量、GPU 开关。

不联网、不读系统配置，只写一个很小的 json：
  优先  <项目根>/data/state.json   （绿色版，跟软件放一起）
  没写权限时退到 %LOCALAPPDATA%/VanityGen/state.json
"""

import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)

MAX_RULES = 32
MAX_RULE_CHARS = 32

DEFAULTS = {
    "lang": "zh",
    "chain": "eth",
    "threads": 0,      # 0 = 跟随 CPU 核数
    "count": 1,
    "use_gpu": False,
    "rules": [{"prefix": "", "suffix": ""}],
}


def _data_dir():
    project = os.path.join(ROOT_DIR, "data")
    try:
        os.makedirs(project, exist_ok=True)
        probe = os.path.join(project, ".write_probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("1")
        os.remove(probe)
        return project
    except OSError:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        fallback = os.path.join(base, "VanityGen")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def path():
    return os.path.join(_data_dir(), "state.json")


def _clean_rules(rules):
    out = []
    if isinstance(rules, list):
        for r in rules[:MAX_RULES]:
            if isinstance(r, dict):
                out.append({
                    "prefix": str(r.get("prefix", ""))[:MAX_RULE_CHARS],
                    "suffix": str(r.get("suffix", ""))[:MAX_RULE_CHARS],
                })
    if not out:
        out = [{"prefix": "", "suffix": ""}]
    return out


def load():
    data = dict(DEFAULTS)
    data["rules"] = [dict(r) for r in DEFAULTS["rules"]]
    try:
        with open(path(), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return data
    if not isinstance(raw, dict):
        return data

    if isinstance(raw.get("lang"), str) and raw["lang"]:
        data["lang"] = raw["lang"]
    if isinstance(raw.get("chain"), str) and raw["chain"]:
        data["chain"] = raw["chain"]
    for key in ("threads", "count"):
        try:
            val = int(raw.get(key))
            if val > 0:
                data[key] = val
        except (TypeError, ValueError):
            pass
    if isinstance(raw.get("use_gpu"), bool):
        data["use_gpu"] = raw["use_gpu"]
    data["rules"] = _clean_rules(raw.get("rules"))
    return data


def save(data):
    payload = {
        "lang": data.get("lang", DEFAULTS["lang"]),
        "chain": data.get("chain", DEFAULTS["chain"]),
        "threads": int(data.get("threads") or 0),
        "count": max(1, int(data.get("count") or 1)),
        "use_gpu": bool(data.get("use_gpu")),
        "rules": _clean_rules(data.get("rules")),
    }
    try:
        tmp = path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path())
        return True
    except OSError:
        return False

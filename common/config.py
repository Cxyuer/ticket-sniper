#!/usr/bin/env python3
"""公共配置：多项目加载、日志、开票时间窗口、票档分组推导"""

import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
LOCAL_CONFIG_PATH = os.path.join(ROOT, "config.local.json")
TIER_MAP_PATH = os.path.join(ROOT, "maoyan", "desktop", "tier_map.json")


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config():
    """config.json 打底，config.local.json 覆盖（本机私有，不进 git）"""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.path.exists(LOCAL_CONFIG_PATH):
        try:
            with open(LOCAL_CONFIG_PATH, encoding="utf-8") as f:
                _merge(cfg, json.load(f))
        except Exception:
            pass
    return cfg


def project_names(cfg=None, only_enabled=True):
    """项目 key 列表。跳过以下划线开头的注释键，以及 enabled=false 的占位项目。"""
    cfg = cfg or load_config()
    out = []
    for k, v in (cfg.get("projects") or {}).items():
        if k.startswith("_"):
            continue
        if only_enabled and isinstance(v, dict) and v.get("enabled") is False:
            continue
        out.append(k)
    return out


def load_project(name=None):
    """取一个项目，套上 defaults。name 为空时取第一个项目。
    返回的 dict 里保证有: name(key), platform, performance_id, show_id,
    target, poll, safety, pre_warm_seconds, sale_time
    """
    cfg = load_config()
    projects = cfg.get("projects") or {}
    if not projects:
        raise SystemExit("config.json 里没有 projects")

    if not name:
        avail = project_names(cfg)
        if not avail:
            raise SystemExit("没有启用的项目。请在 config.local.json 里加一个项目。")
        name = avail[0]

    if name not in projects:
        raise SystemExit(f"没有项目「{name}」，可选: {', '.join(projects)}")

    proj = json.loads(json.dumps(projects[name]))     # 深拷贝，避免改到原配置
    proj["key"] = name
    proj.setdefault("name", name)
    proj.setdefault("platform", "maoyan")

    d = cfg.get("defaults") or {}
    for k in ("poll", "safety", "pre_warm_seconds", "strategy"):
        if k in d:
            if isinstance(d[k], dict):
                base = dict(d[k])
                base.update(proj.get(k) or {})
                proj[k] = base
            else:
                proj.setdefault(k, d[k])

    proj.setdefault("poll", {})
    proj.setdefault("safety", {})
    proj.setdefault("target", {})
    proj.setdefault("strategy", {})
    proj.setdefault("pre_warm_seconds", 60)
    proj.setdefault("sale_time", "")
    return proj


def make_logger(name):
    """写 stdout + ~/.<name>.log"""
    path = os.path.expanduser(f"~/.{name}.log")

    def log(msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        try:
            with open(path, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    return log


def sale_window(proj):
    """返回 (阶段, 到开票还有多少秒)：idle / warm / live"""
    raw = (proj.get("sale_time") or "").strip()
    if not raw:
        return "live", 0            # 未配置定时 = 一直按正常频率跑(售罄等回流票)
    try:
        target = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return "live", 0
    delta = (target - datetime.now()).total_seconds()
    warm = float(proj.get("pre_warm_seconds", 60))
    if delta > warm:
        return "idle", delta
    if delta > 0:
        return "warm", delta
    return "live", delta


# ---------------- 票档分组 ----------------

def load_tier_map():
    """自学习的「fill 颜色 → 区域名列表」映射；没有就返回空"""
    try:
        with open(TIER_MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_tier_map(m):
    try:
        os.makedirs(os.path.dirname(TIER_MAP_PATH), exist_ok=True)
        tmp = TIER_MAP_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, TIER_MAP_PATH)
    except Exception:
        pass


def learn_tiers(areas):
    """有票时用颜色反推票档分组：同色的区域属于同一票档。
    只在学到新东西时落盘，返回是否有更新。"""
    live = [a for a in areas if a.get("available") and a.get("fill")]
    if len(live) < 2:
        return False
    groups = {}
    for a in live:
        groups.setdefault(str(a["fill"]), []).append(a.get("name") or "")
    usable = {k: sorted(set(v)) for k, v in groups.items() if v and "" not in v}
    # 至少两种颜色才说明「颜色能区分票档」；只有一种色时学不出分组，
    # 硬存下来会让「同票档」退化成「全场」
    if len(usable) < 2:
        return False
    m = load_tier_map()
    changed = False
    for color, names in usable.items():
        old = set(m.get(color) or [])
        if set(names) - old:
            m[color] = sorted(old | set(names))
            changed = True
    if changed:
        save_tier_map(m)
    return changed


_PREFIX_RULES = [
    (r"^内场", "内场"),
    (r"^十年同行区?", "十年同行区"),
    (r"^天府俱乐部", "天府俱乐部"),
    (r"主席台", "主席台"),
    (r"^V\d+$", "V看台"),
    (r"^\d+区$", "数字看台"),
]


def area_group(name):
    """名称前缀归组，用于没学到颜色映射前的票档近似"""
    n = (name or "").strip()
    for pat, key in _PREFIX_RULES:
        if re.search(pat, n):
            return key
    return n


def same_tier(target_area, candidate_names):
    """给定目标区域，返回同票档的区域名列表（不含目标本身）
    优先级: 显式 tier_areas > 自学习颜色映射 > 名称前缀归组
    """
    cands = [c for c in candidate_names if c and c != target_area]

    explicit = None
    m = load_tier_map()
    for names in m.values():
        if target_area in names:
            explicit = [c for c in cands if c in names]
            break
    if explicit:
        return explicit

    g = area_group(target_area)
    return [c for c in cands if area_group(c) == g]

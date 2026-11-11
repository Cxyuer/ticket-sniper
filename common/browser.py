#!/usr/bin/env python3
"""浏览器后端门面：按需选「外部 CLI」或 Playwright

上层（seat_watch 等）只调这里的函数，换后端不动业务代码。

选后端的顺序：
    1. 环境变量 TS_BACKEND，或 config 的 browser.backend = cli | playwright → 强制
    2. auto（默认）：配了 browser.cli_command 就用 cli，否则用 Playwright

配置来源：config.json 是公共的（不含个人环境细节），
本机差异写 config.local.json，它被 .gitignore 排除。

tab_id 的差别：外部 CLI 有多个真 tab，需要真 id；Playwright 只有一个页面，
统一用 "main"。所以取 tab 请用 list_tabs()，不要自己拼。
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "maoyan", "desktop", "js")
MAIN_TAB = "main"

_cache = {}


def _config():
    """合并 config.json 与 config.local.json（后者覆盖前者）"""
    def merge(base, over):
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                merge(base[k], v)
            else:
                base[k] = v
        return base

    cfg = {}
    for name in ("config.json", "config.local.json"):
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                part = json.load(f)
        except Exception:
            continue
        cfg = merge(cfg, part) if cfg else part
    return cfg


def _cli_command():
    env = (os.environ.get("TS_BROWSER_CLI") or "").strip()
    if env:
        return env
    return ((_config().get("browser") or {}).get("cli_command") or "").strip()


def _pick():
    if "backend" in _cache:
        return _cache["backend"]

    want = (os.environ.get("TS_BACKEND")
            or (_config().get("browser") or {}).get("backend") or "auto")
    want = str(want).lower()

    if want in ("cli", "legacy-cli"):     # legacy-cli 是旧名，兼容老配置
        name = "cli"
    elif want == "playwright":
        name = "playwright"
    else:
        name = "cli" if _cli_command() else "playwright"

    if name == "cli":
        import common.browser_cli as mod
    else:
        import common.browser_playwright as mod
    _cache["backend"] = name
    _cache["mod"] = mod
    return name


def backend_name():
    _pick()
    return _cache["backend"]


def _mod():
    _pick()
    return _cache["mod"]


# ---------------- 与后端无关 ----------------

def js(name):
    """js 目录下的脚本绝对路径"""
    return os.path.join(JS_DIR, name)


# ---------------- 透传 ----------------

def eval_js(tab_id, js_path=None, expression=None):
    return _mod().eval_js(tab_id, js_path=js_path, expression=expression)


def click_selector(tab_id, selector):
    return _mod().click_selector(tab_id, selector)


def click_text(tab_id, text):
    return _mod().click_text(tab_id, text)


def page_text(tab_id):
    return _mod().page_text(tab_id)


def goto(tab_id, url):
    return _mod().goto(tab_id, url)


def reload(tab_id):
    return _mod().reload(tab_id)


def click_at(tab_id, selector, ox, oy):
    return _mod().click_at(tab_id, selector, ox, oy)


def open_tab(url):
    mod = _mod()
    return bool(getattr(mod, "open_tab", lambda _u: False)(url))


def snapshot(tab_id):
    mod = _mod()
    return getattr(mod, "snapshot", lambda _t: "")(tab_id)


def click_ref(tab_id, ref):
    mod = _mod()
    return bool(getattr(mod, "click_ref", lambda _t, _r: False)(tab_id, ref))


def list_tabs():
    return _mod().list_tabs()


def find_tab(key):
    """按 URL 关键字找 tab；找不到返回 None。
    tab id 会随浏览器重启/标签关闭而失效，所以监控循环里要能重找。"""
    for t in list_tabs():
        if not key or key in (t.get("url") or ""):
            return t.get("tabId")
    return None

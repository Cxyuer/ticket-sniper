#!/usr/bin/env python3
"""浏览器后端：Playwright（自包含，不需要任何外部 CLI）

为什么用 persistent_context：
    登录态存在项目自己的 profile 目录里，第一次人工登录一次，之后所有脚本复用。
    不碰用户日常 Chrome 的 profile，也不会重启它。

为什么用 channel="chrome"：
    直接调系统已装的 Chrome，不需要 `playwright install` 下载浏览器。

注意：headless 容易被票务风控识别，默认有头；配置里可改。
"""

import atexit
import json
import os

DEFAULT_PROFILE = os.path.expanduser("~/.ticket-sniper/chrome-profile")
_pw = None
_ctx = None
_page = None


def _cfg():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "config.json"), encoding="utf-8") as f:
            return json.load(f).get("browser") or {}
    except Exception:
        return {}


def _profile():
    raw = os.environ.get("TS_PROFILE_DIR") or _cfg().get("profile_dir") or DEFAULT_PROFILE
    return os.path.expanduser(raw)


def _headless():
    env = os.environ.get("TS_HEADLESS")
    if env is not None and env != "":
        return env.lower() in ("1", "true", "yes")
    return bool(_cfg().get("headless"))


def _ensure():
    """打开（或复用）持久化上下文，返回当前 page"""
    global _pw, _ctx, _page
    if _page is not None and not _page.is_closed():
        return _page

    from playwright.sync_api import sync_playwright

    profile = _profile()
    os.makedirs(profile, exist_ok=True)

    _pw = sync_playwright().start()
    _ctx = _pw.chromium.launch_persistent_context(
        profile,
        channel=os.environ.get("TS_BROWSER_CHANNEL", "chrome"),
        headless=_headless(),
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1280,900",
        ],
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
    )
    pages = [p for p in _ctx.pages if not p.is_closed()]
    _page = pages[0] if pages else _ctx.new_page()
    return _page


def _cleanup():
    global _pw, _ctx, _page
    try:
        if _ctx is not None:
            _ctx.close()
    except Exception:
        pass
    try:
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    _pw = _ctx = _page = None


atexit.register(_cleanup)


def _parse(val):
    """与 cli 后端保持一致：返回字符串时再尝试解析成 JSON"""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


def eval_js(tab_id, js_path=None, expression=None):
    page = _ensure()
    src = open(js_path, encoding="utf-8").read() if js_path else (expression or "1")
    try:
        return _parse(page.evaluate(src))
    except Exception as e:
        # 页面正在跳转时 execution context 会失效，这一轮当空结果，下一轮重试
        if os.environ.get("TS_DEBUG"):
            print(f"[playwright] eval 失败: {type(e).__name__}: {str(e)[:160]}")
        return None


def click_selector(tab_id, selector):
    page = _ensure()
    try:
        loc = page.locator(selector).first
        loc.click(timeout=3000)
        return True
    except Exception:
        # SVG 元素用 playwright 点不动时，退回 JS 点击
        try:
            return bool(page.evaluate(
                "s=>{var e=document.querySelector(s); if(!e) return false;"
                "e.dispatchEvent(new MouseEvent('click',{bubbles:true})); return true}",
                selector))
        except Exception:
            return False


def click_text(tab_id, text):
    page = _ensure()
    for build in (
        lambda: page.get_by_text(text, exact=False).first,
        lambda: page.locator(f"text={text}").first,
        lambda: page.locator(f"[class*=btn]").filter(has_text=text).first,
    ):
        try:
            loc = build()
            loc.click(timeout=2500)
            return True, ""
        except Exception:
            continue
    return False, ""


def page_text(tab_id):
    page = _ensure()
    try:
        return page.evaluate("document.body.innerText.replace(/\\n+/g,'|')") or ""
    except Exception:
        return ""


def goto(tab_id, url):
    page = _ensure()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return True
    except Exception:
        return False


def reload(tab_id):
    page = _ensure()
    try:
        page.reload(wait_until="domcontentloaded", timeout=30000)
        return True
    except Exception:
        return False


def list_tabs():
    """与 cli 后端同格式：[{tabId, url, title}]"""
    page = _ensure()
    try:
        return [{"tabId": "main", "url": page.url, "title": page.title()}]
    except Exception:
        return []


def open_interactive(url):
    """有头打开页面，等人工回车（首次登录用）"""
    page = _ensure()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    print(f"已打开: {page.url[:100]}")
    print("请在弹出的浏览器里完成登录，然后回到终端按回车…")
    input()
    print("登录态已保存到", _profile())


def click_at(tab_id, selector, ox, oy):
    """在元素的相对坐标处点击（playwright 的 position 是元素内偏移）"""
    page = _ensure()
    try:
        page.locator(selector).first.click(position={"x": ox, "y": oy}, timeout=3000)
        return True
    except Exception:
        try:
            box = page.locator(selector).first.bounding_box()
            if not box:
                return False
            page.mouse.click(box["x"] + ox, box["y"] + oy)
            return True
        except Exception:
            return False

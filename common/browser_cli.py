#!/usr/bin/env python3
"""外部浏览器 CLI 后端：把 evaluate / click / navigate 交给一个命令行工具

这里不绑定任何具体产品——命令由 config.local.json 的
browser.cli_command（或环境变量 TS_BROWSER_CLI）提供。
公共配置里留空，所以默认后端是 Playwright。

要求该 CLI 至少支持：evaluate / click / navigate / reload / list_tabs。

注意一点（踩过）：结果过大时 CLI 不打印 value，而是打印 `output: <文件路径>`，
必须读那个文件，否则拿到 None。
"""

import json
import os
import subprocess

from common.config import load_config


def cli_command():
    """CLI 可执行名：环境变量 > 本机私有配置。都没有就报错。"""
    name = (os.environ.get("TS_BROWSER_CLI") or "").strip()
    if not name:
        name = ((load_config().get("browser") or {}).get("cli_command") or "").strip()
    if not name:
        raise RuntimeError(
            "cli 后端没配置命令。请在 config.local.json 里写 "
            '{"browser": {"cli_command": "<你的浏览器CLI>"}}')
    return name
JS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "maoyan", "desktop", "js")


def run(*args, timeout=60):
    try:
        r = subprocess.run([cli_command()] + list(args),
                           capture_output=True, timeout=timeout)
        return r.returncode == 0, r.stdout.decode("utf-8", "ignore")
    except Exception as e:
        return False, str(e)


def _value_from(out):
    """从 CLI 输出取 value：优先 inline，其次 output 文件里的 JSON"""
    raw = None
    for line in out.splitlines():
        if line.startswith("value:"):
            raw = line[6:].strip()
            break
        if line.startswith("output:"):
            path = line[7:].strip()
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f).get("value")
            except Exception:
                return None
            break
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return raw


def eval_js(tab_id, js_path=None, expression=None):
    """执行 JS 文件或短表达式，返回解析后的值（dict/list/str/None）"""
    args = ["evaluate", "--tab-id", tab_id]
    if js_path:
        args += ["--expression-file", js_path]
    else:
        args += ["--expression", expression or "1"]
    ok, out = run(*args)
    if not ok:
        return None
    return _value_from(out)


def click_selector(tab_id, selector):
    return run("click", "--tab-id", tab_id, "--selector", selector)[0]


def click_text(tab_id, text):
    return run("click", "--tab-id", tab_id, "--text", text)


def page_text(tab_id):
    r = eval_js(tab_id, expression="document.body.innerText.replace(/\\n+/g,'|')")
    return r if isinstance(r, str) else ""


def goto(tab_id, url):
    return run("navigate", "--tab-id", tab_id, "--url", url)[0]


def reload(tab_id):
    return run("reload", "--tab-id", tab_id)[0]


def js(name):
    """js 目录下的脚本绝对路径"""
    return os.path.join(JS_DIR, name)


def click_ref(tab_id, ref):
    """按无障碍快照的 ref 点击（同一文案有多个节点时，比按文本更准）"""
    ok, _ = run("click", "--tab-id", tab_id, "--ref", ref)
    return ok


def snapshot(tab_id):
    """页面无障碍快照（markdown），每行形如 `- generic [ref=e42]: 选座购票`

    注意：CLI 把快照写到文件里、只打印 `output: <路径>`，必须读那个文件。
    """
    ok, out = run("snapshot", "--tab-id", tab_id)
    if not ok:
        return ""
    for line in out.splitlines():
        if line.strip().startswith("output:"):
            path = line.split("output:", 1)[1].strip()
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return ""
    return out


def open_tab(url):
    """开一个新 tab（webview 关掉后自救用）"""
    return run("new_tab", "--url", url)[0]


def list_tabs():
    """与 playwright 后端同格式：[{tabId, url, title}]"""
    ok, out = run("list_tabs")
    if not ok:
        return []
    tabs, cur = [], {}
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("- tabId:"):
            if cur.get("tabId"):
                tabs.append(cur)
            cur = {"tabId": s[len("- tabId:"):].strip()}
        elif s.startswith("url:") and cur:
            cur["url"] = s[len("url:"):].strip().strip('"')
        elif s.startswith("title:") and cur:
            cur["title"] = s[len("title:"):].strip().strip('"')
    if cur.get("tabId"):
        tabs.append(cur)
    return tabs


def click_at(tab_id, selector, ox, oy):
    """在元素的相对坐标处点击（CDP 真实事件；canvas 座位图只认真实输入）"""
    ok, _ = run("click", "--tab-id", tab_id, "--selector", selector,
                "--position-x", str(int(ox)), "--position-y", str(int(oy)))
    return ok

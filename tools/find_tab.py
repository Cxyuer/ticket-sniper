#!/usr/bin/env python3
"""取当前浏览器 tab，用于启动脚本

两种后端的差别：
    cli        —— 多个真 tab，需要按 URL 找
    playwright —— 只有一个页面，固定返回 main

用法:
    python3 tools/find_tab.py 516710       # 找 URL 含 516710 的 tab
    python3 tools/find_tab.py             # 第一个 tab
退出码: 0=找到(打印 tabId) / 1=没找到
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import common.browser as br


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else ""

    if br.backend_name() == "playwright":
        print(br.MAIN_TAB)
        return 0

    tabs = br.list_tabs()
    for t in tabs:
        if not key or key in (t.get("url") or ""):
            print(t["tabId"])
            return 0

    cats = ", ".join((t.get("url") or "")[:50] for t in tabs) or "无"
    sys.stderr.write(f"没找到含「{key}」的 tab。现有: {cats}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())

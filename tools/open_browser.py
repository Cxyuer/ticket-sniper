#!/usr/bin/env python3
"""打开座位页 / 小程序页面，供人工登录一次

Playwright 后端用的是项目自己的 Chrome profile（config.browser.profile_dir），
第一次是未登录状态。跑一次这个脚本，在弹出的浏览器里登录，登录态就存进
profile 目录，之后所有监控脚本直接复用。

用法:
    python3 tools/open_browser.py --project <项目>        # 打开座位页
    python3 tools/open_browser.py --project <项目> --login  # 打开猫眼登录页
    python3 tools/open_browser.py --url https://...      # 随便开一个

注意：会弹出一个独立的 Chrome 窗口（不是你日常那个），
      登录完回终端按回车，窗口关掉，cookie 已落盘。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from common.config import load_project


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--login", action="store_true", help="打开登录页")
    ap.add_argument("--url", default=None)
    args = ap.parse_args()

    if args.url:
        url = args.url
    elif args.login:
        url = "https://passport.maoyan.com/"
    else:
        proj = load_project(args.project)
        url = ("https://show.maoyan.com/myshowfe/trade/seat"
               f"?id={proj['performance_id']}&sId={proj['show_id']}")

    import common.browser as br
    if br.backend_name() != "playwright":
        print(f"当前后端是 {br.backend_name()}，这个脚本只给 Playwright 用。")
        print("要切后端，把 config.json 的 browser.backend 改成 playwright")
        return 1

    import common.browser_playwright as pw
    print(f"profile: {pw._profile()}")
    pw.open_interactive(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""猫眼演出 —— 接口层监控（兜底）

不依赖浏览器/屏幕，锁屏也活着。只回答一个问题：放票了没有。
座位页那两路（选座、同程）都靠渲染，锁屏即失效；这一路是最后的保险。

用法:
    python3 api_watch.py --project <项目>              # 按 config 定时
    python3 api_watch.py --project <项目> --once       # 查一次
    python3 api_watch.py --project <项目> --interval 5 # 固定间隔
    python3 api_watch.py --project <项目> --no-open    # 放票时不自动开页面
    python3 api_watch.py --list                     # 列出所有项目
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from common.config import (load_project, make_logger, project_names,
                           sale_window)
from common.notify import notify

log = make_logger("ts_api")

BASE = "https://show.maoyan.com/maoyansh/myshow/ajax"
REFERER = "https://show.maoyan.com/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def state_path(proj):
    return os.path.expanduser(f"~/.ts_api_{proj['key']}.json")


def http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": REFERER, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def snapshot(proj):
    pid = proj["performance_id"]
    d = (http_json(f"{BASE}/performance/{pid};poi=false") or {}).get("data") or {}
    tk = (http_json(f"{BASE}/performance/{pid}/tickets") or {}).get("data") or []
    tiers = []
    for t in tk:
        price = t.get("ticketPrice") or 0
        if price <= 0:            # 0 元是内部工作票位
            continue
        tiers.append({"price": price, "inv": bool(t.get("hasInventory"))})
    return {
        "name": d.get("name"),
        "status": d.get("ticketStatus"),
        "sale": d.get("saleStatus"),
        "tiers": tiers,
        "ts": time.time(),
    }


def buy_url(proj):
    return f"https://show.maoyan.com/qqw/#/detail/{proj['performance_id']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="config.projects 里的 key")
    ap.add_argument("--list", action="store_true", help="列出项目")
    ap.add_argument("--interval", type=float, default=0,
                    help="固定间隔；0=按 sale_time 自动切换")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("\n".join(project_names()))
        return 0

    proj = load_project(args.project)
    url = buy_url(proj)
    max_price = float(proj["target"].get("max_price") or 99999)
    state_file = state_path(proj)

    log(f"项目 {proj['key']} | {proj.get('name', proj['performance_id'])}")
    log(f"{'固定' if args.interval else '定时'}: "
        f"{args.interval or proj.get('sale_time') or '未配置(一直 live)'}")

    try:
        prev = json.load(open(state_file))
    except Exception:
        prev = {}
    first = True

    while True:
        phase, delta = ("live", 0) if args.interval else sale_window(proj)
        try:
            cur = snapshot(proj)
        except Exception as e:
            log(f"  查询失败: {e}")
            time.sleep(args.interval or 10)
            continue

        tiers_txt = " / ".join(f"¥{t['price']}{'✓' if t['inv'] else '×'}"
                               for t in cur["tiers"]) or "无票档"
        log(f"  status={cur['status']} sale={cur['sale']} | {tiers_txt}")

        if not first:
            prev_inv = {t["price"]: t["inv"] for t in prev.get("tiers", [])}
            hits = [t["price"] for t in cur["tiers"]
                    if t["inv"] and t["price"] <= max_price
                    and not prev_inv.get(t["price"])]
            flipped = (prev.get("status") != cur["status"]
                       or prev.get("sale") != cur["sale"])

            if hits:
                msg = f"¥{'/'.join(map(str, hits))} 有票! 立即下单"
                log(f"🟢🟢 放票! {msg}")
                notify(f"{proj['key']} 放票", msg, speak="有票了，快去下单")
                if not args.no_open:
                    subprocess.Popen(["open", url])
                    log(f"  → 已打开 {url}")
            elif flipped:
                log(f"⚡ 状态变化 {prev.get('status')}→{cur['status']} "
                    f"sale {prev.get('sale')}→{cur['sale']}")
                notify(f"{proj['key']} 状态变化", "场次状态翻转, 请检查")

        prev = cur
        try:
            json.dump(cur, open(state_file, "w"))
        except Exception:
            pass
        first = False

        if args.once:
            return 0

        if args.interval:
            iv = args.interval
        elif phase == "warm":
            iv = float(proj["poll"].get("fast_interval", 1.2))
        elif phase == "idle":
            iv = 30
        else:
            iv = float(proj["poll"].get("api_interval", 10))
        time.sleep(iv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("已停止")

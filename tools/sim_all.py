#!/usr/bin/env python3
"""批量模拟：把一批演出都走到「立即支付」按钮前（订单确认页）

对每个演出：
    详情页 → 选座购票/立即预订 → [票档页] → 座位图 → 选座 → 确认选座 → /qqw/confirm

硬约束（写死，没有开关）：
    · 只点一次「确认选座/提交」进订单页
    · 绝不点「立即支付」，不进收银台
    · 每个演出只买 1 张，挑能买的最便宜档

用法:
    python3 tools/sim_all.py --pids 518646 481224
    python3 tools/sim_all.py --discover 8          # 从推荐流自动抓 8 个在售演出
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import common.browser as br
from common.config import load_config
from maoyan.desktop import seat_watch as sw


def proj_for(pid, max_price=2000):
    cfg = load_config()
    safety = dict(cfg.get("defaults", {}).get("safety") or {})
    return {
        "key": "_sim",
        "performance_id": str(pid),
        "show_id": "",
        "name": "",
        "target": {"area": "", "tier_areas": [], "seat_range": [],
                   "max_price": max_price, "quantity": 1, "viewers": [],
                   "auto_pay": False},
        "restock": {"areas": [], "seat_range": []},
        "safety": safety,
        "poll": {},
    }


def discover(n):
    """从推荐流里挑在售演出（接口免签，能直接翻页）"""
    import urllib.request
    base = "https://show.maoyan.com/maoyansh/myshow/ajax/recommend/performances"
    out = []
    page = 1
    while len(out) < n and page <= 6:
        url = f"{base}?pageNo={page}&pageSize=30&pageSource=1&source=1&cityId=10"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://show.maoyan.com/qqw/"})
        rows = json.loads(urllib.request.urlopen(req, timeout=15).read().decode()).get("data") or []
        for s in rows:
            if s.get("ticketStatus") == 3 and len(out) < n:
                out.append((str(s["performanceId"]), s.get("name", "")[:26],
                            s.get("lowestPrice") or 0))
        page += 1
    return out


def current_tab(retries=10):
    """webview 换 id / 被关掉时 list_tabs 会返回空：先等，实在没有就自己开一个"""
    for _ in range(retries):
        tabs = br.list_tabs()
        if tabs:
            return tabs[0]["tabId"]
        time.sleep(1)
    br.open_tab("https://show.maoyan.com/qqw/")
    time.sleep(5)
    tabs = br.list_tabs()
    if tabs:
        return tabs[0]["tabId"]
    raise RuntimeError("打不开浏览器 tab，请检查 MyFlicker 浏览器")


def run_one(pid, name="", cap=2000):
    proj = proj_for(pid, cap)
    tab = current_tab()
    br.goto(tab, sw.DETAIL_URL.format(pid=pid))
    time.sleep(4)

    sid = sw.attach_from_detail(tab, proj)
    if sid == "CONFIRM" or sw.at_confirm_page(tab):
        return "✅ 订单页（无需选座）", str(br.eval_js(tab, expression="location.href"))
    if not sid:
        return "⚪ 没票/进不去", ""

    st = sw.scan(tab)
    avail = sw.area_level(st)
    if avail:
        res = sw.run_stages(tab, proj, ("all",), auto_submit=True, stop_at_confirm=True)
    elif not (st.get("total") or 0) and sw.grid_scan(tab).get("seats"):
        res = sw.run_canvas_only(tab, proj, auto_submit=True, stop_at_confirm=True)
    else:
        return "⚪ 座位图无票（sId=" + sid + "）", ""

    if res == "done" and sw.at_confirm_page(tab):
        return "✅ 订单页", str(br.eval_js(tab, expression="location.href"))
    if sw.at_confirm_page(tab):
        return "✅ 订单页", str(br.eval_js(tab, expression="location.href"))
    return f"⚠️ 未到订单页（{res}）", str(br.eval_js(tab, expression="location.href"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pids", nargs="*", default=[])
    ap.add_argument("--discover", type=int, default=0)
    ap.add_argument("--cap", type=float, default=2000, help="单张票价上限")
    ap.add_argument("--gap", type=float, default=60, help="每场之间的间隔秒数（防限流）")
    args = ap.parse_args()

    jobs = [(p, "", args.cap) for p in args.pids]
    if args.discover:
        jobs += [(p, n, min(args.cap, mp or args.cap)) for p, n, mp in discover(args.discover)]

    if not jobs:
        print("没给演出：用 --pids 或 --discover N")
        return 1

    print(f"共 {len(jobs)} 场，全部止步订单确认页（不点立即支付）")
    results = []
    for i, (pid, name, cap) in enumerate(jobs, 1):
        print(f"\n[{i}/{len(jobs)}] {pid} {name}")
        try:
            status, url = run_one(pid, name, cap)
        except Exception as e:
            status, url = f"❌ 异常 {e}", ""
        print(f"   → {status} {url}")
        results.append((pid, name, status))
        if i < len(jobs):
            print(f"   … 等 {args.gap:.0f} 秒再跑下一场")
            time.sleep(args.gap)

    ok = sum(1 for r in results if r[2].startswith("✅"))
    print(f"\n汇总：{ok}/{len(results)} 到了订单确认页")
    for pid, name, status in results:
        print(f"  {pid:<8} {status:<24} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

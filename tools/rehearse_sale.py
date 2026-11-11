#!/usr/bin/env python3
"""首发模拟：到点只点「第一下」，绝不选座、绝不下单

流程：
    详情页待机 → 开售瞬间点「立即购买」进座位图 → 读区域/可售/底部 CTA → 结束

写死不做的事（没有开关）：
    · 不点选任何座位
    · 不点「确认选座」「提交」「去结算」「立即支付」
    · 不进入订单确认页，不产生订单

用法:
    python3 tools/rehearse_sale.py --project hxy
    python3 tools/rehearse_sale.py --project hxy --at "2026-11-12 12:22:00" --lead 20

开售时间默认取项目配置里的 sale_time；没配就用 --at。
"""

import argparse
import os
import random
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import common.browser as br
from common.config import load_project
from common.notify import notify

JS_DIR = os.path.join(ROOT, "maoyan", "desktop", "js")
JS_AREA = os.path.join(JS_DIR, "seat_area.js")
JS_CTA = os.path.join(JS_DIR, "seat_cta.js")

# 只有这些文案才算「开售了」，才允许点第一下
BUY_TEXTS = ("立即购买", "选座购票", "选座购买", "立即预订", "立即抢购", "特惠购买", "立即购票")
# 看到这些说明没票了，直接收工
OUT_OF_STOCK = ("缺货登记", "已售罄", "缺票登记", "暂时无票")

READ_CTA = r"""
(() => {
  const out = [];
  const nodes = [...document.querySelectorAll('div,button,a,span')];
  for (const e of nodes) {
    const t = (e.innerText || '').trim();
    if (!t || t.length > 12) continue;
    if (!/购买|购票|预订|抢购|选座|缺货|售罄|登记|预约/.test(t)) continue;
    if (out.indexOf(t) < 0) out.push(t);
  }
  return JSON.stringify(out.slice(0, 12));
})()
"""

READ_SEAT_URL = "location.href"

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def cta_texts(tab):
    import json
    v = br.eval_js(tab, expression=READ_CTA)
    try:
        return json.loads(v) if isinstance(v, str) else (v or [])
    except Exception:
        return []


def click_text(tab, text):
    """按可见文案点底部按钮（后端差异由门面处理）"""
    return br.click_text(tab, text)


def parse_at(raw):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%H:%M:%S"):
        try:
            t = datetime.strptime(raw, fmt)
        except Exception:
            continue
        if fmt == "%H:%M:%S":
            now = datetime.now()
            t = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
        return t
    raise SystemExit(f"看不懂时间: {raw}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--at", default=None, help="开售时间，默认取配置里的 sale_time")
    ap.add_argument("--lead", type=float, default=20, help="开售前多少秒切到高频轮询")
    ap.add_argument("--give-up", type=float, default=900, help="开售后多少秒还没进座位图就放弃")
    args = ap.parse_args()

    proj = load_project(args.project or "")
    pid = str(proj["performance_id"])
    detail = f"https://show.maoyan.com/qqw/#/detail/{pid}"

    raw_at = args.at or (proj.get("sale_time") or "").strip()
    if not raw_at:
        raise SystemExit("没有开售时间：配置里填 sale_time，或用 --at")

    log(f"模拟演出 {proj.get('name')} | {proj.get('city_name') or ''}")
    log(f"详情页   {detail}")

    tab = br.find_tab(pid)
    if not tab:
        tabs = br.list_tabs()
        tab = tabs[0]["tabId"] if tabs else None
    if not tab:
        raise SystemExit("找不到浏览器 tab，请先在浏览器打开这个演出页")

    br.goto(tab, detail)
    time.sleep(4)

    target = parse_at(raw_at)
    log(f"开售时间 {target:%Y-%m-%d %H:%M:%S} | 距现在 {(target - datetime.now()).total_seconds():.0f} 秒")

    clicked = False
    deadline = None
    last_beat = 0
    while True:
        now = datetime.now()
        delta = (target - now).total_seconds()
        if deadline is None and delta <= 0:
            deadline = time.time() + args.give_up

        texts = cta_texts(tab)
        buy = [t for t in texts if any(b in t for b in BUY_TEXTS)]
        sold = [t for t in texts if any(s in t for s in OUT_OF_STOCK)]

        if buy or sold:
            log(f"页面按钮: {texts}")

        if buy:
            log(f"✅ 开售了，出现「{buy[0]}」→ 点第一下")
            ok = click_text(tab, buy[0])
            log(f"点击{'成功' if ok else '失败'}，等页面跳转…")
            clicked = True
            break

        if delta > args.lead:
            if time.time() - last_beat > 60:
                log(f"待机中，距开售 {delta / 60:.1f} 分钟")
                last_beat = time.time()
            time.sleep(min(5, max(1, delta - args.lead)))
            continue

        if deadline and time.time() > deadline:
            log("❌ 开售后一直没出现购买按钮，放弃（页面可能仍是预约/售罄）")
            notify("首发模拟结束", "开售后没出现购买按钮", popup=False)
            return 1

        # 高频段：刷新 + 读按钮
        if random.random() < 0.35:
            br.reload(tab)
        time.sleep(0.8)

    # —— 点完第一下就只观察，不再点任何东西 ——
    time.sleep(4)
    href = str(br.eval_js(tab, expression=READ_SEAT_URL) or "")
    log(f"落地页   {href}")

    s_id = ""
    if "sId=" in href:
        s_id = href.split("sId=")[1].split("&")[0]
        log(f"场次 sId {s_id}")

    if "trade/seat" in href:
        st = br.eval_js(tab, js_path=JS_AREA) or {}
        avail = [a for a in (st.get("available") or []) if a.get("name")]
        cta = br.eval_js(tab, js_path=JS_CTA) or {}
        log(f"座位页  区域 {st.get('total')} | 区级可售 {len(avail)} | soldOut={st.get('soldOut')}")
        log(f"底部 CTA {cta.get('best')}")
        if avail:
            names = "、".join(a["name"] for a in avail[:8])
            log(f"可售区域 {names}")
        notify("首发模拟完成", f"已进座位图：区域 {st.get('total')}，可售 {len(avail)}", popup=False)
    else:
        log("没进座位页（可能弹了场次选择或需要验证），已按要求停手")
        notify("首发模拟结束", "点了第一下，但没进座位图", popup=False)

    log("模拟结束：未选座、未确认、未进入订单页")
    return 0


if __name__ == "__main__":
    sys.exit(main())

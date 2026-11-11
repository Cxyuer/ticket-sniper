#!/usr/bin/env python3
"""猫眼演出 —— 座位监控 + 分级抢座（抢到就锁，不犹豫）

为什么分级：
    第一次点进首选区域时，座位常已被别人锁住；继续盯同一区域只是等死。
    所以按「精确 → 同票档 → 全场」逐级放宽，每级失败就刷新页面重来，
    一旦拿到可提交状态立刻连点两次锁座。

    锁座后不付款没有任何损失（订单超时自动取消），所以策略是激进的：
    先锁住，再叫人付款。

三级策略：
    1. exact  只点 config 的首选区域，座位号须在 seat_range 内
    2. tier   同一票档的所有区域（票档靠颜色自学习，学不到按名称前缀归组）
    3. all    全场任意可售区域，不限座位号

用法：
    python3 seat_watch.py --project <项目> --tab <tab-id>
    python3 seat_watch.py --project <项目> --tab <tab-id> --area 内场A2区
    python3 seat_watch.py --check --tab <tab-id>     # 只看不点
    python3 seat_watch.py --once  --tab <tab-id>     # 只跑一轮
    python3 seat_watch.py --no-submit                # 选好座但不锁

前置：浏览器已登录，且 tab 停在座位页。
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import common.browser as br
from common.config import (learn_tiers, load_project, make_logger,
                           sale_window, same_tier)
from common.notify import notify

log = make_logger("ts_seat")

JS_AREA = br.js("seat_area.js")
JS_CTA = br.js("seat_cta.js")
JS_GRID = br.js("seat_grid.js")
JS_VIEWERS = br.js("viewers.js")
JS_MAIN_BTN = br.js("find_main_btn.js")

# 支付/下单页特征。实测（2026-11-11 八仙过海 ¥380）确认页 CTA 是「立即支付」，
# 且页面出现「应付」，这两条不认出来就会误以为还停在选座页
PAY_WORDS = ["微信支付", "支付宝", "银行卡", "收银台", "确认支付",
             "剩余支付时间", "支付订单"]
CONGEST = ["前方拥堵", "请稍后重试", "系统繁忙", "排队中", "稍后再试",
           "人数过多", "请求过多", "网络繁忙", "手慢了"]
SOLD_WORDS = ["已被锁定", "已被抢", "已售出", "座位已售", "无票", "余票不足"]
# 还没开票的页面特征（出现这些说明要等首发，不是等回流）
NOT_ON_SALE_WORDS = ["开售提醒", "预约", "即将开售", "预售", "倒计时",
                     "未开始", "即将开始", "开售时间"]

STAGES = ("exact", "tier", "all")          # 首发：逐级放宽
RESTOCK_STAGES = ("restock",)              # 回流：默认全场通吃
STAGE_LABEL = {"exact": "精确区域", "tier": "同票档区域",
               "all": "全场任意", "restock": "回流(全场)"}


# ---------------- 页面 ----------------

def seat_url(proj):
    return ("https://show.maoyan.com/myshowfe/trade/seat"
            f"?id={proj['performance_id']}&sId={proj['show_id']}")


def scan(tab):
    return br.eval_js(tab, js_path=JS_AREA) or {}


def href_of(tab):
    """当前地址；tab 已失效时返回空串（不抛异常）"""
    v = br.eval_js(tab, expression="location.href")
    return "" if v is None else str(v)


def resolve_tab(tab, proj, hijack=False):
    """每轮重新定位座位页 tab，返回 (tab_id, 是否已在座位页)。

    tab id 会随浏览器复用而变（8→12→13），不能缓存启动时拿到的那个。
    顺序：真在座位页的 > 当前 tab 还停在座位页 > URL 含本场 ID 的 >
    任何可用 tab（仅在 hijack=True 时，用来把被导走的 webview 拉回来）。
    """
    key = str(proj["performance_id"])
    seat_hit = same_show = spare = None
    for t in br.list_tabs() or []:
        tid, url = t.get("tabId"), t.get("url") or ""
        if not tid:
            continue
        if spare is None:
            spare = tid            # 单 webview 后端里这就是唯一那个
        if key not in url:
            continue
        if seat_hit is None and ("trade/seat" in url or "seat-area" in url):
            seat_hit = tid
        if same_show is None:
            same_show = tid
    if seat_hit:
        return seat_hit, True
    href = href_of(tab) if tab else ""
    if href and ("trade/seat" in href or "seat-area" in href) and key in href:
        return tab, True
    if same_show:
        return same_show, False
    if hijack and spare:
        return spare, False
    return None, False


_nav_at = 0.0


def ensure_page(tab, proj):
    """确保 tab 停在座位页；被切走或未登录跳走时导航回去"""
    global _nav_at
    href = href_of(tab)
    if not href:
        # tab id 失效（标签被关/浏览器重启），由主循环负责重找，这里不刷日志
        return False
    if (("trade/seat" in href or "seat-area" in href)
            and f"={proj['performance_id']}" in href):
        return True

    if "passport." in href:
        # 未登录：座位图根本不会加载，区域数会一直是 0，必须说清楚
        _login_warn(proj)
        return False

    # 同一分钟内只喊一次，避免导航失败时每 6 秒刷一行
    if time.time() - _nav_at > 60:
        _nav_at = time.time()
        log(f"  ⚠️ 不在座位页({href[:60]}), 重新导航")
    br.goto(tab, seat_url(proj))
    time.sleep(5)
    href = href_of(tab)
    if "passport." in href:
        # 未登录时是「先到座位页、再被重定向」到登录页，所以这里必须再判一次
        _login_warn(proj)
        return False
    return "trade/seat" in href or "seat-area" in href


_login_warned = set()


def _login_warn(proj):
    """登录失效只吼一次，别刷屏"""
    if proj["key"] in _login_warned:
        return
    _login_warned.add(proj["key"])
    log("❌ 登录已失效（页面跳到了 passport.maoyan.com）")
    log(f"   → Playwright 后端: python3 tools/open_browser.py --project {proj['key']}")
    log("     在弹出的浏览器里登录一次，登录态会存进 profile 目录")
    log("   → cli 后端: 直接在你接管的浏览器里登录猫眼")
    notify("抢票监控中断", "猫眼登录失效，座位监控已停", speak="登录失效了")


# ---------------- 从详情页点进座位图 ----------------
#
# 座位页地址带 sId，而 sId 只有在「详情页 → 立即预订/购买 → 票档页 → 选档」之后
# 才会出现在 URL 里。开售前拿不到，所以模拟或首次进入都得自己点进去。

DETAIL_URL = "https://show.maoyan.com/qqw/#/detail/{pid}"
BUY_TEXTS = ("立即购买", "选座购票", "选座购买", "立即预订", "立即抢购",
             "特惠购买", "立即购票")
SOLD_TEXTS = ("缺货登记", "已售罄", "暂时无票", "无票")
CONFIRM_TEXTS = ("去选座", "立即选座", "去下单", "确定", "确认", "下一步")

JS_STATE = """
(() => {
  const out = {url: location.href, cta: [], tiers: [], bottom: []};
  const txts = [];
  for (const e of document.querySelectorAll('div,button,span')) {
    const t = (e.innerText || '').trim();
    if (t && t.length <= 14 && txts.indexOf(t) < 0) txts.push(t);
  }
  out.cta = txts.filter(t => /购买|购票|预订|抢购|缺货|售罄|登记|预约/.test(t)).slice(0, 10);
  out.bottom = txts.filter(t => /确定|确认|选座|下一|请选择/.test(t)).slice(0, 6);
  out.tiers = [...document.querySelectorAll('.wrap-item')].map(e => ({
    txt: (e.innerText || '').replace(/\\n/g, ' ').trim(),
    out: /outOfStock/.test(e.className)
  }));
  return JSON.stringify(out);
})()
"""

JS_MODAL = """
(() => {
  const boxes = [...document.querySelectorAll('[class*=dialog],[class*=modal],[class*=popup],[class*=confirm],[class*=agree]')]
    .filter(e => e.offsetParent !== null && /须知|已知悉|同意/.test(e.innerText || ''));
  if (!boxes.length) return 'none';
  const box = boxes[boxes.length - 1];
  const btns = [...box.querySelectorAll('div,button,span,a')]
    .filter(e => /已知悉|同意|确认|知道了/.test((e.innerText || '').trim()));
  if (!btns.length) return 'none';
  return (btns[btns.length - 1].innerText || '').trim();
})()
"""

JS_MARK_TIER = """
(() => {
  const rows = [...document.querySelectorAll('.wrap-item')]
    .filter(e => !/outOfStock/.test(e.className));
  document.querySelectorAll('[data-ts-tier]').forEach(e => e.removeAttribute('data-ts-tier'));
  const el = rows[%d];
  if (!el) return 'none';
  el.setAttribute('data-ts-tier', '1');
  return 'ok';
})()
"""


def page_state(tab):
    v = br.eval_js(tab, expression=JS_STATE)
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


def _price_of(text):
    m = re.search(r"(\d{2,5})", str(text).replace(",", ""))
    return int(m.group(1)) if m else 0


def _pick_tier(rows, proj):
    """预算内 + 首选区域关键词，都取不到就挑最便宜的"""
    tgt = proj.get("target") or {}
    cap = int(tgt.get("max_price") or 0)
    want = str(tgt.get("area") or "")
    cand = [t for t in rows if not cap or _price_of(t["txt"]) <= cap] or rows
    if want:
        hit = [t for t in cand if want[:2] in t["txt"]]
        if hit:
            cand = hit
    return sorted(cand, key=lambda t: _price_of(t["txt"]))[0]


def _sid_from(url):
    if "sId=" in (url or ""):
        return url.split("sId=")[1].split("&")[0]
    return None


JS_DATE = """
(() => {
  const cards = [...document.querySelectorAll('[class*=date__wrapper],[class*=date-wrapper],[class*=calendar] [class*=item]')]
    .filter(e => e.offsetParent !== null && !/disabled|gray|sold/i.test(String(e.className))
                 && /\d{1,2}-\d{1,2}|\d{1,2}日/.test(e.innerText || ''));
  if (!cards.length) return 'none';
  const txt = (cards[0].innerText || '').replace(/\n/g, ' ').trim();
  cards[0].setAttribute('data-ts-date', '1');
  return txt.slice(0, 20);
})()
"""


def _click_date_card(tab):
    """多场次详情页要先点日期卡才出购买入口。返回点到的日期文案 / None"""
    txt = br.eval_js(tab, expression=JS_DATE)
    if not isinstance(txt, str) or txt == "none":
        return None
    log(f"   先选日期「{txt}」")
    br.click_selector(tab, "[data-ts-date='1']")
    return txt


REF_LINE = re.compile(r"\[ref=(e\d+)\]:\s*(.+?)\s*$", re.M)


def _ref_click_buy(tab, pid):
    """多场次列表里每行都有一个「选座购票」，按文本点只会打到外层容器。
    这里读无障碍快照，拿到真实节点的 ref 逐个点，直到离开详情页。"""
    snap = br.snapshot(tab) or ""
    hits = [(r, t.strip()) for r, t in REF_LINE.findall(snap)
            if any(b in t for b in BUY_TEXTS)]
    if not hits:
        return False
    for ref, txt in hits[:4]:
        log(f"   按节点点「{txt}」({ref})")
        br.click_ref(tab, ref)
        time.sleep(3)
        if f"detail/{pid}" not in href_of(tab):
            return True
    return False


JS_SESSION = """
(() => {
  const all = [...document.querySelectorAll('.session-item')];
  const rows = all.filter(e => !String(e.className).includes('stockout'));
  if (!rows.length) return 'none';
  document.querySelectorAll('[data-ts-session]').forEach(e => e.removeAttribute('data-ts-session'));
  rows[0].setAttribute('data-ts-session', '1');
  return (rows[0].innerText || '').replace(/s+/g, ' ').trim().slice(0, 24) || 'ok';
})()
"""


def _pick_session(tab):
    """多场次场子点「选座购票」会先弹出场次面板（.session-list），要挑一个非缺货场次"""
    for _ in range(6):
        txt = br.eval_js(tab, expression=JS_SESSION)
        if isinstance(txt, str) and txt not in ("none", ""):
            log(f"   选场次「{txt}」")
            if not br.click_selector(tab, "[data-ts-session='1']"):
                _js_click_sel(tab, "[data-ts-session='1']")
            time.sleep(3)
            return True
        time.sleep(1)
    return False


JS_MARK_TEXT = """
(() => {
  const want = %s;
  const norm = function (e) { return ((e.innerText || '').replace(/\s+/g, '')); };
  const all = [...document.querySelectorAll('div,span,a,button')]
    .filter(e => e.offsetParent !== null);
  let nodes = all.filter(e => norm(e) === want);
  if (!nodes.length) {
    // 允许「想看 + 立即预订」这种带前缀的底部按钮，但别把长标题算进来
    nodes = all.filter(e => {
      const t = norm(e);
      return t.endsWith(want) && t.length <= want.length + 8;
    });
  }
  if (!nodes.length) return 'none';
  // 文案最短的最具体；同样长就取页面最下方的（底部 CTA）
  nodes.sort(function (a, b) {
    const la = norm(a).length, lb = norm(b).length;
    if (la !== lb) return la - lb;
    return b.getBoundingClientRect().top - a.getBoundingClientRect().top;
  });
  document.querySelectorAll('[data-ts-pick]').forEach(e => e.removeAttribute('data-ts-pick'));
  nodes[0].setAttribute('data-ts-pick', '1');
  return 'ok';
})()
"""


def _js_click_sel(tab, sel):
    """按选择器用 DOM click() 点（真实点击不可用时的兜底）"""
    expr = ("(() => { const e = document.querySelector(%s); if (!e) return 'none';"
            " e.click(); return 'ok'; })()" % json.dumps(sel))
    return br.eval_js(tab, expression=expr) == "ok"


def click_buy(tab, text):
    """按文案点按钮。

    踩过：直接 --text 点击会撞 Playwright 的 strict mode（页面上「演唱会」同时匹配
    分类入口和演出名里的「演唱会」），于是永远点不动。所以先自己挑一个元素、打上
    唯一标记，再用唯一选择器点它；真实点击失败再退回 DOM click()。
    """
    js = JS_MARK_TEXT % json.dumps(re.sub(r"\s+", "", str(text)), ensure_ascii=False)
    if br.eval_js(tab, expression=js) != "ok":
        return False
    if br.click_selector(tab, "[data-ts-pick='1']"):
        return True
    return _js_click_sel(tab, "[data-ts-pick='1']")


def js_click(tab, text):
    """只走 DOM click()（不产生真实输入事件）"""
    js = JS_MARK_TEXT % json.dumps(re.sub(r"\s+", "", str(text)), ensure_ascii=False)
    if br.eval_js(tab, expression=js) != "ok":
        return False
    return _js_click_sel(tab, "[data-ts-pick='1']")


JS_NOTICE = """
(() => {
  const t = (document.body.innerText || '');
  return /我已知悉|已阅读并同意|请阅读并同意/.test(t) ? 'need' : 'none';
})()
"""


def _accept_notice(tab, rounds=3):
    """点「选座购票/立即预订」后常弹购票须知，必须点「我已知悉，并确认」才继续。
    之前按 dialog class 找，匹配不到；改成看页面里有没有这行字，再按文案点。"""
    for _ in range(rounds):
        if br.eval_js(tab, expression=JS_NOTICE) != "need":
            return False
        for label in ("我已知悉，并确认", "我已知悉", "已阅读并同意", "同意并继续"):
            if click_buy(tab, label):
                log(f"   购票须知 → 点「{label}」")
                time.sleep(1.5)
                break
        else:
            return False
    return True


def attach_from_detail(tab, proj):
    """详情页 → 立即预订 → 票档 → 座位图。成功返回 sId，没票/失败返回 None"""
    pid = str(proj["performance_id"])
    st = page_state(tab)
    if f"detail/{pid}" not in (st.get("url") or ""):
        log("   → 打开演出详情页")
        br.goto(tab, DETAIL_URL.format(pid=pid))
        time.sleep(4)
        st = page_state(tab)

    buy = [t for t in st.get("cta", []) if any(b in t for b in BUY_TEXTS)]
    if not buy and _click_date_card(tab):
        time.sleep(3)
        st = page_state(tab)
        buy = [t for t in st.get("cta", []) if any(b in t for b in BUY_TEXTS)]
    if not buy:
        sold = [t for t in st.get("cta", []) if any(s in t for s in SOLD_TEXTS)]
        log(f"   详情页没有购买入口（{sold[0] if sold else '无按钮'}）")
        return None

    log(f"   点「{buy[0]}」")

    def _landed():
        h = href_of(tab)
        return ("trade/seat" in h) or ("seat-area" in h) or at_confirm_page(tab)

    def _wait_land(seconds):
        """跳转要 2~3 秒，别一秒钟就判失败"""
        for _ in range(int(seconds)):
            time.sleep(1)
            if _landed():
                return True
        return False

    # 最多点三轮：有票的场子第一下就跳；先弹须知/场次面板的要接着点
    for _ in range(3):
        click_buy(tab, buy[0])
        if _wait_land(6):
            break
        for label in ("我已知悉，并确认", "我已知悉", "已阅读并同意"):
            if click_buy(tab, label):
                log(f"   购票须知 → 点「{label}」")
                break
        if _wait_land(4):
            break
        _pick_session(tab)
        if _wait_land(4):
            break

    # 票档页有时已经预选好（底部直接是「去选座」），有时要自己挑档；
    # 页面刚渲染时这两个都读不到，所以轮询等一下，别把空白当缺货。
    st = {}
    for _ in range(8):
        time.sleep(1)
        st = page_state(tab)
        url = st.get("url") or ""
        if "trade/seat" in url or "seat-area" in url:
            return _sid_from(url)
        rows = [t for t in st.get("tiers", []) if not t.get("out")]
        if rows or [t for t in st.get("bottom", [])
                    if "请选择" not in t and "可选座" not in t
                    and any(c in t for c in CONFIRM_TEXTS)]:
            break

    if "trade/seat" in (st.get("url") or "") or "seat-area" in (st.get("url") or ""):
        return _sid_from(st.get("url"))

    def _confirm_btn(state):
        return [t for t in state.get("bottom", [])
                if "请选择" not in t and "可选座" not in t
                and any(c in t for c in CONFIRM_TEXTS)]

    if "ticket-level" not in (st.get("url") or ""):
        log("   没进票档页（可能已直达座位图或未就绪）")
        return _sid_from(st.get("url"))

    btn = _confirm_btn(st)
    if not btn:
        rows = [t for t in st.get("tiers", []) if not t.get("out")]
        if not rows:
            log("   票档页没有可点的档（可能是缺货登记）")
            return None
        pick = _pick_tier(rows, proj)
        log(f"   选票档「{pick['txt']}」")
        br.eval_js(tab, expression=JS_MARK_TIER % rows.index(pick))
        if not br.click_selector(tab, "[data-ts-tier='1']"):
            _js_click_sel(tab, "[data-ts-tier='1']")
        time.sleep(2)
        st = page_state(tab)
        btn = _confirm_btn(st)

    if btn:
        log(f"   点「{btn[0]}」进座位图")
        br.click_text(tab, btn[0])
        time.sleep(5)
        st = page_state(tab)

    return _sid_from(st.get("url"))


_sid_cache = None     # 点进去拿到的场次号，配置里没填时用它


_outage_at = 0.0      # 上次「断开太久」提醒的时间，用来做冷却
_last_ok = None       # 上一次成功读到座位页的时间


def _outage(miss):
    """座位页短时读不到是常态（页面在跳转、webview 换 id），别用弹窗打断人。

    只有真的断了几分钟才提醒，而且提醒过一次就静默半小时。
    """
    global _outage_at
    if miss == 1:
        log("… 座位页暂时读不到（可能在跳转），继续重试")
    if _last_ok is None:
        return
    gap = time.time() - _last_ok
    if gap < 180 or time.time() - _outage_at < 1800:
        return
    _outage_at = time.time()
    mins = f"{gap / 60:.0f} 分钟"
    log(f"⚠️ 座位页已断开 {mins}，仍未恢复")
    # 不弹模态窗（会抢焦点、打断你正在做的事），只出横幅 + 响一声
    notify("座位监控中断", f"座位页已断开 {mins}，请在浏览器里重新打开",
           speak="座位监控中断", popup=False)


def page_text(tab):
    t = br.page_text(tab)
    return t if isinstance(t, str) else ""


def at_confirm_page(tab):
    """订单确认页（/qqw/confirm）——还没付钱，也没提交"""
    return "/confirm" in href_of(tab)


def is_pay_page(tab):
    """真正的支付页：URL 变了，或页面出现支付方式。注意「应付」在确认页也有，
    不能拿它当判据（踩过：导致没跳转也报成功）"""
    if "/pay" in href_of(tab):
        return True
    return any(w in page_text(tab) for w in PAY_WORDS)


def seat_cta(tab):
    return br.eval_js(tab, js_path=JS_CTA) or {}


def _js_arr(items):
    return "[" + ",".join('"' + str(s).replace('"', '\\"') + '"' for s in items) + "]"


def set_allowlists(tab, proj):
    """把白/黑名单注入页面，供 find_main_btn.js 用"""
    safety = proj.get("safety") or {}
    expr = ("window.__TS_ALLOW=" + _js_arr(safety.get("allow_cta") or [])
            + ";window.__TS_DENY=" + _js_arr(safety.get("deny_cta") or [])
            + ';"ok"')
    br.eval_js(tab, expression=expr)


def main_btn(tab):
    """白名单内的底部按钮（用于确认弹窗）"""
    r = br.eval_js(tab, js_path=JS_MAIN_BTN) or {}
    return r.get("best")


def click_xy(tab, x, y):
    br.eval_js(tab, expression=f"(function(){{window.__TS_X={x};window.__TS_Y={y};}})()")
    return br.eval_js(tab, js_path=br.js("click_xy.js"))


def click_area(tab, area):
    if area.get("id") and br.click_selector(tab, "#" + area["id"]):
        return True
    return bool(click_xy(tab, area["x"], area["y"]))


# ---------------- 挑区域 / 挑座位 ----------------

def _size_cut(st):
    """区域级 / 座位级的分界尺寸。

    座位图可以缩放，固定 60px 会把缩小后的区域全判成座位（实测缩到 392px 宽时
    区域只有 19px 中位）。所以用「有名字区域」的尺寸中位数的一半当分界；
    拿不到中位数（纯座位图，座位没有名字）时退回 60px。
    """
    med = st.get("medianSize") or 0
    return max(8, med * 0.5) if med else 60


def area_level(st):
    """区域级（相对大块）且可售"""
    cut = _size_cut(st)
    return [a for a in (st.get("available") or [])
            if a.get("name") and max(a.get("w", 0), a.get("h", 0)) >= cut]


def seat_level(st):
    """座位级（相对小块）且可售"""
    cut = _size_cut(st)
    return [a for a in (st.get("available") or [])
            if 6 <= max(a.get("w", 0), a.get("h", 0)) < cut]


def candidates(stage, avail, proj):
    """按阶段给出要尝试的区域（有序）"""
    tgt = proj.get("target") or {}
    target = tgt.get("area") or ""
    names = [a["name"] for a in avail]
    by_name = {a["name"]: a for a in avail}

    if stage == "exact":
        return [by_name[target]] if target in by_name else []

    if stage == "tier":
        explicit = tgt.get("tier_areas") or []
        picked = ([n for n in explicit if n in by_name] if explicit
                  else same_tier(target, names))
        return [by_name[n] for n in picked]

    if stage == "restock":
        # 回流档位与首发完全独立：只看 restock.areas，绝不继承 target 的配置。
        # 没配 = 全场都可以；配了就只抢这些档位，没票就继续等，不退回全场。
        want = (proj.get("restock") or {}).get("areas") or []
        if want:
            return [a for a in avail if any(w in a["name"] for w in want)]
        return avail

    tried = set()
    for s in ("exact", "tier"):
        tried |= {a["name"] for a in candidates(s, avail, proj)}
    return [a for a in avail if a["name"] not in tried]


def seat_range_for(stage, proj):
    """首发用 target.seat_range；回流用 restock.seat_range（默认不限）"""
    if stage == "restock":
        rs = (proj.get("restock") or {}).get("seat_range") or []
        return rs or None
    if stage == "all":
        return None
    return (proj.get("target") or {}).get("seat_range")


def seat_number(txt):
    """取座位号：优先「N排M号」的 M，其次「M号」，最后首个数字
    （只认座位号，避免「12排23号」的排号 12 误命中 [1,80]）"""
    txt = txt or ""
    m = re.search(r"(\d+)\s*排\s*(\d+)\s*[号座]?", txt)
    if m:
        return int(m.group(2))
    m = re.search(r"(\d+)\s*[号座]", txt)
    if m:
        return int(m.group(1))
    nums = re.findall(r"\d{1,4}", txt)
    return int(nums[0]) if nums else None


def pick_seat(seats, seat_range):
    """按座位号范围挑；范围内没有就退回第一个可售"""
    if not seats:
        return None
    if seat_range:
        lo, hi = (list(seat_range) + [None, None])[:2]
        if lo is not None:
            for s in seats:
                n = seat_number((s.get("name") or "") + " " + (s.get("id") or ""))
                if n is not None and lo <= n <= hi:
                    return s
    return seats[0]


# ---------------- 锁座 ----------------

def lock_seat(tab, proj, max_rounds=8):
    """连点底部 CTA 直到进支付页。不犹豫、不等确认、锁住再说。"""
    delay = float((proj.get("safety") or {}).get("confirm_delay", 0.6))
    for i in range(max_rounds):
        if is_pay_page(tab):
            return "pay"

        cta = seat_cta(tab)
        best = cta.get("best") if cta.get("found") else None
        if best and best.get("enabled"):
            log(f"   锁座第{i + 1}击: 点「{best['text']}」({best['x']},{best['y']})")
            click_xy(tab, best["x"], best["y"])
            time.sleep(delay)
            continue

        btn = main_btn(tab)
        if btn:                                  # 弹了确认框
            log(f"   确认弹窗: 点「{btn['text']}」")
            br.click_text(tab, btn["text"])
            time.sleep(delay)
            continue

        t = page_text(tab)
        if any(w in t for w in CONGEST):
            log("   ⏳ 拥堵, 快速重试")
            time.sleep(0.7)
            continue
        if any(w in t for w in SOLD_WORDS):
            log("   ✖ 座位已被抢/锁定")
            return "lost"
        break

    return "pay" if is_pay_page(tab) else "unknown"


# ---------------- canvas 座位图 ----------------
#
# 实测（2026-11-11 青海体育中心 ¥28 场）：点区域后 SVG 会塌缩，座位改由 canvas 绘制，
# 元素层面读不到任何座位，只能读像素 + 用 CDP 真实坐标点击。

GRID_SEL = "#sdk-seat-container"


def grid_scan(tab):
    return br.eval_js(tab, js_path=JS_GRID) or {}


def selected_seat(tab):
    """从页面文案里读已选座位，返回 (排, 座) 或 None（如「D1区 13排112座」）"""
    t = page_text(tab)
    m = re.search(r"(\d+)\s*排\s*(\d+)\s*[座号]", t)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def grid_pick(tab, seat_range, tries=8):
    """在 canvas 座位图里点一个座位。返回 selected / no-seat"""
    g = grid_scan(tab)
    if not g.get("found"):
        return "no-seat"
    cands = g.get("seats") or []
    if not cands:
        return "no-seat"
    log(f"     canvas 座位图: 可点 {len(cands)} 个点位")

    for c in cands[:tries]:
        if not br.click_at(tab, GRID_SEL, c["ox"], c["oy"]):
            continue
        time.sleep(0.7)
        got = selected_seat(tab)
        if not got:
            continue
        row, num = got
        if seat_range:
            lo, hi = (list(seat_range) + [None, None])[:2]
            if lo is not None and not (lo <= num <= hi):
                log(f"     {row}排{num}座 超出范围 {seat_range}, 取消重选")
                br.click_at(tab, GRID_SEL, c["ox"], c["oy"])   # 再点一次取消
                time.sleep(0.4)
                continue
        log(f"     ✅ 选中 {row}排{num}座 ({c['ox']},{c['oy']})")
        return "selected"

    log("     试了多个点位都没选中")
    return "no-seat"


# ---------------- 提交（止步订单页） ----------------
#
# 模拟要求：走到「立即支付」按钮就停。所以只点一次「确认选座/提交」，
# 到 /qqw/confirm 就算完成，绝不继续点「立即支付」。

SUBMIT_TEXTS = ("确认选座", "提交", "确定", "去结算", "下一步")


def confirm_once(tab):
    """点一次提交，停在订单确认页。返回 done / failed"""
    if at_confirm_page(tab):
        return "done"
    cta = seat_cta(tab)
    best = cta.get("best") if cta.get("found") else None
    if not best or not best.get("enabled"):
        log("     选座后 CTA 仍不可提交（座位可能已被锁）")
        return "failed"
    if best.get("text") not in SUBMIT_TEXTS:
        log(f"     CTA 是「{best.get('text')}」，不在提交白名单，不乱点")
        return "failed"
    log(f"     点「{best['text']}」进订单页")
    click_xy(tab, best["x"], best["y"])
    time.sleep(5)
    return "done" if at_confirm_page(tab) else "failed"


# ---------------- canvas 座位图（无区域层） ----------------
#
# 有的场子没有 SVG 区域块，座位一开始就全画在 canvas 上（实测 LPL 观赛：
# svg path = 0、canvas = 42）。这种情况不能按「区域 → 座位」走，直接像素找座。

JS_SEAT_TIER = """
(() => {
  const rows = [...document.querySelectorAll('.ticket-wrap')]
    .filter(e => !/disable/i.test(String(e.className)));
  if (!rows.length) return 'none';
  if (rows.some(e => /selected|active/i.test(String(e.className)))) return 'already';
  const price = function (e) {
    const m = ((e.innerText || '').match(/(\d{2,5})/) || [0, 0]);
    return parseInt(m[1], 10) || 0;
  };
  rows.sort(function (a, b) { return price(a) - price(b); });
  document.querySelectorAll('[data-ts-seat-tier]').forEach(e => e.removeAttribute('data-ts-seat-tier'));
  rows[0].setAttribute('data-ts-seat-tier', '1');
  return (rows[0].innerText || '').replace(/\s+/g, '').slice(0, 12);
})()
"""


def ensure_seat_tier(tab):
    """座位页顶部的价格票档（¥280/¥480…）没选的话，座位点不动"""
    r = br.eval_js(tab, expression=JS_SEAT_TIER)
    if not isinstance(r, str) or r in ("none", "already", ""):
        return False
    log(f"   选价格票档「{r}」")
    if not br.click_selector(tab, "[data-ts-seat-tier='1']"):
        _js_click_sel(tab, "[data-ts-seat-tier='1']")
    time.sleep(2)
    return True


def run_canvas_only(tab, proj, auto_submit=True, stop_at_confirm=False):
    g = grid_scan(tab)
    n = len(g.get("seats") or [])
    if not n:
        return "nostock"
    log(f"🟢 canvas 座位图（无区域层）: 可点 {n} 个座位点位")
    ensure_seat_tier(tab)
    seat_range = (proj.get("target") or {}).get("seat_range") or None
    if grid_pick(tab, seat_range) != "selected":
        return "failed"
    if not auto_submit:
        log("     --no-submit: 已选座，不提交")
        return "done"
    if stop_at_confirm:
        return confirm_once(tab)

    cta = seat_cta(tab)
    best = cta.get("best") if cta.get("found") else None
    if not best or not best.get("enabled"):
        return "failed"
    return lock_seat(tab, proj)


# ---------------- 单次尝试 ----------------

def attempt_area(tab, area, proj, stage, auto_submit=True, stop_at_confirm=False):
    """点区域 → 点座位 → 锁座。返回 pay/lost/no-seat/selected/unknown"""
    seat_range = seat_range_for(stage, proj)

    log(f"  → 点区域「{area['name']}」({area['x']},{area['y']})")
    click_area(tab, area)
    time.sleep(2.2)

    # 点完区域要等页面响应：SVG 场馆立刻出座位级元素，
    # canvas 场馆要等座位图渲染（实测 5~6 秒），所以轮询而不是死等 2.2 秒
    seats, grid = [], {}
    for _ in range(8):
        time.sleep(1.0)
        seats = seat_level(scan(tab))
        if seats:
            break
        grid = grid_scan(tab)
        if grid.get("seats"):
            break

    st = scan(tab)
    if seats:
        log(f"     座位级可售 {len(seats)} 个（SVG）")
        seat = pick_seat(seats, seat_range)
        if not seat:
            return "no-seat"
        log(f"     选座 ({seat['x']},{seat['y']}) 范围={seat_range or '不限'}")
        if seat.get("id"):
            br.click_selector(tab, "#" + seat["id"])
        else:
            click_xy(tab, seat["x"], seat["y"])
        time.sleep(0.9)
    else:
        # SVG 里没有座位级元素 → 这个场馆用 canvas 画座位
        n = len(grid.get("seats") or [])
        log(f"     无 SVG 座位级元素（区域 {st.get('total')}），canvas 可点 {n} 个")
        if grid_pick(tab, seat_range) != "selected":
            return "no-seat"

    if not auto_submit:
        log("     --no-submit: 已选座，不锁")
        return "selected"

    if stop_at_confirm:
        return confirm_once(tab)

    cta = seat_cta(tab)
    best = cta.get("best") if cta.get("found") else None
    if not best or not best.get("enabled"):
        log("     选座后 CTA 仍不可提交（座位可能已被锁）")
        return "lost"

    log("     CTA 可提交 → 立刻锁座")
    res = lock_seat(tab, proj)
    log(f"     锁座结果: {res}")
    return res


# ---------------- 实名观演人 / 下单 ----------------
#
# 约定：观演人由用户在启动前写进 config（target.viewers），
# 运行时不打断、不弹框，按配置选人后直接点「立即支付」锁座。
# 没配观演人就绝不自动支付——宁可停在确认页，也不能选错人。

def viewers_state(tab):
    return br.eval_js(tab, js_path=JS_VIEWERS) or {}


def ensure_viewers(tab, proj):
    """按配置勾选实名观演人。返回 (ok, 已选名单, 原因)"""
    want = [str(v).strip() for v in ((proj.get("target") or {}).get("viewers") or [])]
    if not want:
        return False, [], "未配置 target.viewers"

    st = viewers_state(tab)
    if not st.get("found"):
        return False, [], "确认页没找到观演人列表"

    items = st.get("items") or []
    names = [i["name"] for i in items]
    missing = [w for w in want if not any(w in n for n in names)]
    if missing:
        return False, st.get("selected") or [], f"配置的观演人不在列表: {missing}"

    for w in want:
        exact = next((n for n in names if w in n), None)
        cur = next((i for i in items if i["name"] == exact), None)
        if cur and not cur["selected"]:
            if not br.click_text(tab, exact):
                return False, st.get("selected") or [], f"点选观演人失败: {exact}"
            time.sleep(0.6)

    st = viewers_state(tab)
    sel = st.get("selected") or []
    need = st.get("need")
    if need is not None and len(sel) < need:
        return False, sel, f"只选了 {len(sel)} 位，页面要求 {need} 位"
    return True, sel, "ok"


def click_pay_button(tab):
    """点确认页的「立即支付」。
    踩过：按文本点会命中外层 div，页面不跳转。真实可点的是
    button.primary-btn-md（页面里有两个，其中一个是隐藏的重下单按钮），
    所以先给可见的那个打临时 id，再用 CDP 点它。"""
    r = br.eval_js(tab, expression="""
(function(){
  var bs = [].slice.call(document.querySelectorAll('button.primary-btn-md'))
    .filter(function(b){ var r=b.getBoundingClientRect(); return r.width>10 && r.height>10; });
  if (!bs.length) return null;
  var b = bs[0];
  b.id = 'ts-pay-btn';
  var r = b.getBoundingClientRect();
  return {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2),
          text: (b.innerText||'').replace(/\\s+/g,'')};
})()
""")
    if not r:
        return False
    log(f"     按钮「{r.get('text') or '立即支付'}」({r['x']},{r['y']})")
    return br.click_selector(tab, "#ts-pay-btn")


def submit_order(tab, proj):
    """选观演人 → 点立即支付（真正锁座）。返回是否已进入支付页。"""
    ok, sel, why = ensure_viewers(tab, proj)
    if not ok:
        log(f"  ❌ {why} —— 停在确认页，不点支付")
        notify("观演人未就绪", why, speak="观演人有问题，请手动处理")
        return False
    log(f"  ✅ 观演人: {', '.join(sel)}")

    log("  → 点「立即支付」锁座")
    if not click_pay_button(tab):
        log("  ⚠️ 没找到可点的支付按钮")
        notify("支付按钮未找到", "确认页没定位到「立即支付」", speak="支付按钮没找到")
        return False
    time.sleep(4)

    if is_pay_page(tab):
        log("  💳 已进入支付页 —— 订单已创建，请完成付款")
        notify("已下单，去支付",
               f"{proj.get('name', '')} 座位已锁，请完成支付",
               speak="订单已创建，快去支付")
        return True

    log("  ⚠️ 点支付后没看到支付页，请人工检查")
    notify("支付状态未知", "已点立即支付但没进支付页，请检查", speak="支付状态未知")
    return False


# ---------------- 主流程 ----------------

def run_stages(tab, proj, stages=STAGES, auto_submit=True, stop_at_confirm=False):
    """有票时按 stages 推进。
    返回 done（已到订单/支付页） / failed（有票但没抢到） / nostock（无票）
    """
    safety = proj.get("safety") or {}
    max_tries = int(safety.get("max_area_tries", 3))
    refresh = bool(safety.get("refresh_on_fail", True))

    st = scan(tab)
    if learn_tiers(st.get("allAreas") or []):
        log("  🎓 学到新票档颜色分组（tier_map.json 已更新）")

    avail = area_level(st)
    if not avail:
        # 没有区域块但 canvas 上有座位 → 纯 canvas 座位图，直接像素选座
        if not (st.get("total") or 0) and grid_scan(tab).get("seats"):
            return run_canvas_only(tab, proj, auto_submit, stop_at_confirm)
        return "nostock"
    log(f"🟢 可售区域 {len(avail)} 个: " + ", ".join(a["name"] for a in avail[:8])
        + ("…" if len(avail) > 8 else ""))

    for stage in stages:
        cands = candidates(stage, avail, proj)
        if not cands:
            if stage == "restock" and ((proj.get("restock") or {}).get("areas") or []):
                log("  · 回流指定档位当前无票，继续等（不会退回全场）")
            else:
                log(f"  · [{stage}] {STAGE_LABEL[stage]}: 无候选, 跳过")
            continue

        log(f"  ▶ [{stage}] {STAGE_LABEL[stage]}: {len(cands)} 个候选"
            f" ({', '.join(a['name'] for a in cands[:6])})")

        for area in cands[:max_tries]:
            res = attempt_area(tab, area, proj, stage, auto_submit, stop_at_confirm)
            if res == "pay":
                return "done"
            if res == "selected":
                return "done"

        if not refresh:
            continue
        log("  ↻ 本级失败, 刷新页面重来")
        br.reload(tab)
        time.sleep(4)
        if not ensure_page(tab, proj):
            return "failed"
        st = scan(tab)
        learn_tiers(st.get("allAreas") or [])
        avail = area_level(st)
        if not avail:
            log("  刷新后已无可售区域")
            return "failed"
        log(f"  刷新后可售 {len(avail)} 个")

    return "failed"


# ---------------- 首发 / 回流 ----------------
#
# 首发：按用户配置的区域/票档精准抢（exact → tier → all）
# 回流：别人退票/超时释放的余票，默认「全场都可以」，用户配了档位才收窄
# auto：先首发；抢失败或过了一段时间自动转回流

def allowed_areas(stage, avail, proj):
    return candidates(stage, avail, proj)


def resolve_phase(proj, first_misses):
    mode = str(proj.get("mode") or "auto").lower()
    rs = proj.get("restock") or {}

    if mode == "restock":
        return "restock", "指定回流模式"
    if mode == "first":
        return "first", "指定首发模式"

    # auto
    if not (proj.get("sale_time") or "").strip():
        return "restock", "未配置开票时间 → 直接抢回流"

    try:
        st_dt = datetime.strptime(proj["sale_time"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return "restock", "开票时间格式异常 → 抢回流"

    mins = (datetime.now() - st_dt).total_seconds() / 60.0
    threshold = float(rs.get("switch_after_minutes", 5))
    if mins > threshold:
        return "restock", f"首发已过 {mins:.0f} 分钟 → 转回流"
    if first_misses >= int(rs.get("switch_after_miss", 1)):
        return "restock", f"首发抢失败 {first_misses} 次 → 转回流"
    return "first", "首发抢票"


def reload_proj(proj, args):
    """运行中重读 config，返回 (新配置, 是否变化)。

    场景：首发没抢到、临时决定回流只抢某些档位 —— 改配置即生效，不用重启进程。
    命令行覆盖（--area/--mode）在重读后重新套上，避免被文件值冲掉。
    """
    try:
        fresh = load_project(proj["key"])
    except Exception:
        return proj, False
    if _sid_cache and not (fresh.get("show_id") or "").strip():
        fresh["show_id"] = _sid_cache   # 自己点进去拿到的场次号，比对时也得算上
    if getattr(args, "area", None):
        fresh.setdefault("target", {})["area"] = args.area
    if getattr(args, "mode", None):
        fresh["mode"] = args.mode

    same = (json.dumps(fresh, sort_keys=True, ensure_ascii=False)
            == json.dumps(proj, sort_keys=True, ensure_ascii=False))
    return fresh, not same


def resolve_auto_pay(proj, args):
    """--no-submit/--pay 优先；没配观演人则强制关闭（宁可不付，不能选错人）"""
    ap = bool((proj.get("target") or {}).get(
        "auto_pay", (proj.get("safety") or {}).get("auto_pay", False)))
    if getattr(args, "no_submit", False):
        ap = False
    if getattr(args, "pay", False):
        ap = True
    viewers = [str(v) for v in ((proj.get("target") or {}).get("viewers") or [])]
    return ap and bool(viewers)


def detect_phase(tab, proj, first_misses=0):
    """判断当前该用哪种模式。

    优先看「用户怎么配的」，其次看现场状态——因为开票与否、售罄与否
    页面上一眼就能看出来，不该让用户去猜：
      现场有余票      → 直接抢（阶段无所谓，first 即可）
      出现开售提醒/预约/倒计时 → 还没开票，等首发
      已开票且全是「缺货登记」 → 售罄，等回流
    兜底才用 sale_time 推断。
    """
    mode = str(proj.get("mode") or "auto").lower()
    if mode in ("first", "restock"):
        return mode, "配置指定"

    st = scan(tab)
    if area_level(st):
        return "first", "现场有余票 → 直接抢"

    t = page_text(tab)
    if any(w in t for w in NOT_ON_SALE_WORDS):
        return "first", "页面显示未开票 → 等首发"
    if "缺货登记" in t:
        return "restock", "已开票但售罄 → 等回流"

    return resolve_phase(proj, first_misses)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="config.projects 里的 key")
    ap.add_argument("--tab", default=os.environ.get("TS_TAB_ID", ""))
    ap.add_argument("--area", default=None, help="临时覆盖首选区域")
    ap.add_argument("--check", action="store_true", help="只看状态, 不点")
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    ap.add_argument("--no-submit", action="store_true", help="选座但不锁座（模拟）")
    ap.add_argument("--from-detail", action="store_true",
                    help="不在座位页时，自己从详情页点进票档再到座位图")
    ap.add_argument("--to-confirm", action="store_true",
                    help="到订单确认页就停，不点「立即支付」（模拟用）")
    ap.add_argument("--pay", action="store_true", help="强制走到点「立即支付」")
    ap.add_argument("--mode", choices=["auto", "first", "restock"],
                    help="auto=首发没抢到自动转回流；first=只抢首发；restock=直接抢回流")
    args = ap.parse_args()

    proj = load_project(args.project)
    if args.area:
        proj["target"]["area"] = args.area

    # 自动支付开关：--no-submit 强制关，--pay 强制开，否则看配置
    auto_pay = bool((proj.get("target") or {}).get(
        "auto_pay", (proj.get("safety") or {}).get("auto_pay", False)))
    if args.no_submit:
        auto_pay = False
    if args.pay:
        auto_pay = True

    tgt = proj["target"]
    viewers = [str(v) for v in (tgt.get("viewers") or [])]
    if auto_pay and not viewers:
        log("⚠️ 配置了自动支付但没写 target.viewers —— 已降级为只到确认页")
        auto_pay = False

    # 启动前确认清单：这些就是要人工核对的东西，跑起来后不再打断
    log("=" * 46)
    log(f"项目     {proj['key']} | {proj.get('name')}")
    if args.mode:
        proj["mode"] = args.mode
    mode = str(proj.get("mode") or "auto").lower()
    rs = proj.get("restock") or {}
    rs_areas = rs.get("areas") or []
    log(f"模式     {mode} | 回流范围 "
        f"{'全场任意' if not rs_areas else '、'.join(rs_areas)}")
    log(f"首选区域 {tgt.get('area')} | 座位号 {tgt.get('seat_range') or '不限'}")
    log(f"最高价   {tgt.get('max_price')} | 数量 {tgt.get('quantity', 1)}")
    log(f"观演人   {', '.join(viewers) if viewers else '（未配置）'}")
    log(f"自动支付 {'开：会选观演人并点「立即支付」锁座' if auto_pay else '关：只到订单确认页'}")
    log("↑ 以上为启动前确认项；运行中不会再询问")
    log("=" * 46)

    # Playwright 后端只有一个页面，tab_id 固定为 main
    if not args.tab and br.backend_name() == "playwright":
        args.tab = br.MAIN_TAB

    if not args.tab:
        log("⚠️ 缺 --tab（或环境变量 TS_TAB_ID）")
        log(f"   座位页: {seat_url(proj)}")
        return 1

    if args.check:
        if not ensure_page(args.tab, proj):
            return 1
        st = scan(args.tab)
        avail = area_level(st)
        log(f"区域 {st.get('total')} | 区级可售 {len(avail)} | "
            f"座级可售 {len(seat_level(st))} | soldOut={st.get('soldOut')}")
        names = [a["name"] for a in avail]
        if names:
            log(f"同票档候选: {same_tier(proj['target'].get('area'), names)[:10]}")
        cta = seat_cta(args.tab)
        log(f"底部 CTA: {cta.get('best')}")
        return 0

    phase, delta = sale_window(proj)
    if phase == "idle":
        log(f"距开票 {delta / 3600:.1f} 小时，待机")
    elif phase == "warm":
        log(f"⏰ 距开票 {delta:.0f} 秒，预热高频模式")
    else:
        log("已进入开票时段，正常监控")

    seat_iv = float(proj["poll"].get("seat_interval", 5))
    fast_iv = float(proj["poll"].get("fast_interval", 1.2))
    loop = 0
    done = False

    tab = args.tab
    global _last_ok, _sid_cache
    _last_ok = time.time()
    miss = 0          # 连续多少次取不到地址（tab 已失效）
    first_misses = 0  # 首发模式下有票但没抢到的次数
    last_phase = None
    while True:
        loop += 1
        proj, cfg_changed = reload_proj(proj, args)
        if _sid_cache and not (proj.get("show_id") or "").strip():
            proj["show_id"] = _sid_cache      # 自己点进去拿到的场次号，别被配置覆盖掉
        if cfg_changed:
            log("♻️ 配置已热加载（改了 config 不用重启）")
            log(f"   回流档位: {(proj.get('restock') or {}).get('areas') or '全场任意'}")
        phase, delta = sale_window(proj)

        if phase == "idle" and not done:
            time.sleep(min(30, max(5, delta - float(proj.get("pre_warm_seconds", 60)))))
            continue

        # tab id 会随浏览器复用而变（8→12→13），所以每轮重新解析一次，
        # 不要相信启动时拿到的那个 id。
        # 页面跳转瞬间 evaluate/list_tabs 都可能返回空，那不算失联，别报警。
        # 连续几轮都没有座位页时，把 webview 拉回座位页自救（省得叫人）。
        cur, on_seat = resolve_tab(tab, proj, hijack=(miss >= 3))
        if cur:
            if cur != tab:
                log(f"🔄 tab 已变化 → {cur[-4:]}" + ("" if on_seat else "（不在座位页，导航回去）"))
                tab = cur
            miss = 0
            _last_ok = time.time()
        else:
            miss += 1
            _outage(miss)
            time.sleep(max(seat_iv, 5))
            continue

        # 没有场次号就进不了座位页：要么配置里有，要么自己点进去
        if args.from_detail and not (proj.get("show_id") or "").strip():
            sid = attach_from_detail(tab, proj)
            if not sid:
                log("   这一轮没进去（没票或按钮还没变成可购买），等下一轮")
                time.sleep(max(seat_iv, 8))
                continue
            _sid_cache = sid
            proj["show_id"] = sid
            log(f"✅ 已进座位图，sId={sid}")

        if not ensure_page(tab, proj):
            log("   不在座位页（加 --from-detail 可自动从详情页点进去）")
            time.sleep(seat_iv)
            continue
        set_allowlists(tab, proj)

        if done:
            if loop % 50 == 0:
                log(f"❤️ 心跳 {loop}（已锁座，保持观察）")
            time.sleep(seat_iv)
            continue

        cur_phase, why = detect_phase(tab, proj, first_misses)
        if cur_phase != last_phase:
            log(f"🎯 模式切换 → {cur_phase}（{why}）")
            last_phase = cur_phase
        stages = RESTOCK_STAGES if cur_phase == "restock" else STAGES

        res = run_stages(tab, proj, stages, auto_submit=not args.no_submit,
                         stop_at_confirm=args.to_confirm)
        if res == "done":
            done = True
            if at_confirm_page(tab):
                if resolve_auto_pay(proj, args):
                    submit_order(tab, proj)
                else:
                    log("✅ 已到订单确认页 —— 自动操作停止（未开启自动支付）")
                    notify("已到订单页", "座位已选好，请确认并完成支付",
                           speak="已到订单页，快去支付")
            else:
                log("✅ 已进支付页 —— 自动操作停止，请立刻付款")
                notify("已锁座！", "订单已创建，立即完成支付", speak="锁座成功，快去付款")
        elif res == "failed" and cur_phase == "first":
            first_misses += 1
            log(f"  ✖ 首发没抢到（第 {first_misses} 次），下次按回流处理")
        elif loop % 20 == 1:
            st = scan(tab)
            log(f"❤️ 第{loop}轮 | 区域 {st.get('total')} | "
                f"区级可售 {len(area_level(st))} | 模式 {cur_phase}")

        if args.once:
            log("--once: 结束")
            return 0

        time.sleep(fast_iv if phase == "warm" else seat_iv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("已停止")

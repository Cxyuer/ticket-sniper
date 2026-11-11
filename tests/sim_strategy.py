#!/usr/bin/env python3
"""seat_watch 分级策略的离线仿真

真实场景没法复现（放票是随机的），所以用假页面把状态机跑一遍：
    首选区域点进去没座位 → 刷新 → 同票档区域点进去有座位 → 锁座 → 进支付页

跑: python3 tests/sim_strategy.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import maoyan.desktop.seat_watch as sw


def area(name, w=90, h=70):
    return {"id": "id_" + name, "name": name, "x": 100, "y": 200,
            "w": w, "h": h, "fill": "#38a169", "available": True}


def seat(n, w=14, h=14):
    return {"id": "s%d" % n, "name": "%d号" % n, "x": 300 + n, "y": 400,
            "w": w, "h": h, "fill": "#38a169", "available": True}


class FakePage:
    """模拟座位页的三种状态: 区域图 / 座位图 / 支付页"""

    def __init__(self, scenario):
        self.scenario = scenario          # 每次「进入区域」时给出的座位
        self.view = "areas"
        self.seats = []
        self.pay = False
        self.clicks = []                  # 记录点过的区域名
        self.reloads = 0
        self.cta_presses = 0

    # --- 给 seat_watch 用的假接口 ---
    def scan(self, tab):
        if self.pay:
            return {"total": 0, "available": [], "soldOut": True, "allAreas": []}
        if self.view == "areas":
            return {"total": len(self.scenario["areas"]), "soldOut": False,
                    "available": self.scenario["areas"], "allAreas": self.scenario["areas"]}
        return {"total": len(self.seats), "soldOut": not self.seats,
                "available": self.seats, "allAreas": self.seats}

    def click_area(self, tab, a):
        name = a["name"]
        self.clicks.append(name)
        seats = self.scenario["seats"].get(name)
        if seats is None:                  # 点进去没座位（被人锁了）
            self.view = "areas"
            self.seats = []
        else:
            self.view = "seats"
            self.seats = seats
        return True

    def seat_cta(self, tab):
        if self.pay:
            return {"found": False}
        enabled = self.view == "seats" and bool(self.seats)
        return {"found": True, "best": {
            "text": "提交" if enabled else "请选择座位",
            "cls": "btn" if enabled else "btn opc40",
            "enabled": enabled, "x": 1646, "y": 893, "w": 125, "bottom": 918}}

    def page_text(self, tab):
        return "支付方式|微信支付" if self.pay else "座位图"

    def click_xy(self, tab, x, y):
        if self.view == "seats" and self.seats:
            self.cta_presses += 1
            if self.cta_presses >= 2:      # 点两次 = 锁座成功
                self.pay = True
        return {"ok": True, "tag": "div", "text": "btn"}

    def reload(self, tab):
        self.reloads += 1
        self.view = "areas"
        self.seats = []
        return True


def install(page):
    sw.scan = page.scan
    sw.click_area = page.click_area
    sw.seat_cta = page.seat_cta
    sw.page_text = page.page_text
    sw.click_xy = page.click_xy
    sw.is_pay_page = lambda tab: page.pay
    sw.br.reload = page.reload
    sw.br.eval_js = lambda *a, **k: None
    sw.br.page_text = lambda tab: page.page_text(tab)
    sw.br.click_text = lambda tab, t: (True, "")
    sw.br.click_selector = lambda tab, s: True
    sw.ensure_page = lambda tab, proj: True


def run(name, page, proj, expect_pay, expect_clicks):
    install(page)
    got = sw.run_stages("tab", proj, auto_submit=True)
    ok = (got == ('done' if expect_pay else 'failed')) and page.clicks == expect_clicks
    print(f"{'✅' if ok else '❌'} {name}")
    print(f"     返回={got} 期望={'done' if expect_pay else 'failed'} | 点过区域={page.clicks} "
          f"期望={expect_clicks} | 刷新={page.reloads} 连击={page.cta_presses}")
    return ok


def project(area_name="内场A1区", seat_range=(1, 80)):
    return {
        "key": "demo", "name": "测试", "performance_id": "1", "show_id": "2",
        "target": {"area": area_name, "tier_areas": [], "seat_range": list(seat_range),
                   "max_price": 1976},
        "poll": {"seat_interval": 0, "fast_interval": 0},
        "safety": {"confirm_delay": 0, "refresh_on_fail": True, "max_area_tries": 3},
    }




def check_phase_rules():
    """首发/回流判定：不碰浏览器，纯逻辑回归"""
    from datetime import datetime, timedelta
    cases = []

    base = {"key": "t", "target": {}, "restock": {"switch_after_minutes": 5,
                                                  "switch_after_miss": 1}}
    # 1) 明确指定回流
    cases.append(("mode=restock", dict(base, mode="restock"), 0, "restock"))
    # 2) 明确指定首发
    cases.append(("mode=first", dict(base, mode="first"), 0, "first"))
    # 3) auto + 没开票时间 → 直接回流
    cases.append(("auto/无 sale_time", dict(base, mode="auto", sale_time=""), 0, "restock"))
    # 4) auto + 开票在将来 → 首发
    fut = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    cases.append(("auto/未来开票", dict(base, mode="auto", sale_time=fut), 0, "first"))
    # 5) auto + 开票已过 30 分钟 → 回流
    past = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    cases.append(("auto/开票已过30分", dict(base, mode="auto", sale_time=past), 0, "restock"))
    # 6) auto + 首发抢失败过 → 回流
    cases.append(("auto/首发失败1次", dict(base, mode="auto", sale_time=fut), 1, "restock"))

    ok_all = True
    for name, proj, misses, expect in cases:
        got, why = sw.resolve_phase(proj, misses)
        ok = got == expect
        ok_all &= ok
        print(f"{'✅' if ok else '❌'} {name:20} → {got:8} (期望 {expect}) {why}")
    return ok_all


def check_restock_areas():
    """回流候选：默认全场，配了档位就收窄，档位没票退回全场"""
    proj = {"key": "t", "target": {"area": "A1区"},
            "restock": {"areas": []}}
    avail = [area("A1区"), area("B区"), area("C区")]

    got = [a["name"] for a in sw.candidates("restock", avail, proj)]
    ok1 = got == ["A1区", "B区", "C区"]
    print(f"{'✅' if ok1 else '❌'} 回流默认全场 → {got}")

    proj2 = {"key": "t", "target": {"area": "A1区"}, "restock": {"areas": ["B区"]}}
    got2 = [a["name"] for a in sw.candidates("restock", avail, proj2)]
    ok2 = got2 == ["B区"]
    print(f"{'✅' if ok2 else '❌'} 回流指定档位 → {got2}")

    # 配了档位但当时无票 → 只等待，不退回全场
    proj3 = {"key": "t", "target": {"area": "A1区"}, "restock": {"areas": ["Z区"]}}
    got3 = [a["name"] for a in sw.candidates("restock", avail, proj3)]
    ok3 = got3 == []
    print(f"{'✅' if ok3 else '❌'} 指定档位无票 → 不退回全场 {got3} (期望 [])")

    # 回流与首发完全独立：不看 target 的配置
    proj4 = {"key": "t", "target": {"area": "A1区", "tier_areas": ["A1区"]},
             "restock": {"areas": ["B区"]}}
    got4 = [a["name"] for a in sw.candidates("restock", avail, proj4)]
    ok4 = got4 == ["B区"]
    print(f"{'✅' if ok4 else '❌'} 回流不继承首发档位 → {got4} (期望 ['B区'])")

    # 首发配了档位、回流没配 → 回流仍是全场
    proj5 = {"key": "t", "target": {"area": "A1区"}, "restock": {"areas": []}}
    got5 = [a["name"] for a in sw.candidates("restock", avail, proj5)]
    ok5 = got5 == ["A1区", "B区", "C区"]
    print(f"{'✅' if ok5 else '❌'} 首发档位不影响回流 → {got5} (期望全场)")
    return ok1 and ok2 and ok3 and ok4 and ok5




def check_detect_phase():
    """按现场状态判模式：有票→直接抢；未开票→等首发；售罄→等回流"""
    real_scan, real_text = sw.scan, sw.page_text

    def scenario(avail_names, text):
        sw.scan = lambda tab: {"total": len(avail_names),
                               "available": [area(n) for n in avail_names],
                               "allAreas": [area(n) for n in avail_names]}
        sw.page_text = lambda tab: text

    base = {"key": "t", "mode": "auto", "target": {}, "restock": {}}
    cases = [
        ("现场有票 → 直接抢", ["A1区"], "¥380|确认选座", "first"),
        ("未开票（有开售提醒）", [], "即将开售|开售提醒", "first"),
        ("已开票售罄（缺货登记）", [], "¥380 缺货登记 ¥280 缺货登记", "restock"),
    ]
    ok_all = True
    for name, avail, text, expect in cases:
        scenario(avail, text)
        got, why = sw.detect_phase("tab", dict(base), 0)
        ok = got == expect
        ok_all &= ok
        print(f"{'✅' if ok else '❌'} {name:22} → {got:8} (期望 {expect}) {why}")

    # 配置强制优先
    scenario([], "¥380 缺货登记")
    got, why = sw.detect_phase("tab", dict(base, mode="first"), 0)
    ok = got == "first"
    ok_all &= ok
    print(f"{'✅' if ok else '❌'} {'配置 first 覆盖售罄':22} → {got:8} (期望 first) {why}")

    sw.scan, sw.page_text = real_scan, real_text
    return ok_all




def check_auto_pay_rules():
    """自动支付：没配观演人一律不自动付"""
    class A:
        no_submit = False
        pay = False

    p1 = {"target": {"auto_pay": True, "viewers": ["某人"]}}
    p2 = {"target": {"auto_pay": True, "viewers": []}}
    p3 = {"target": {"auto_pay": False, "viewers": ["某人"]}}

    r1 = sw.resolve_auto_pay(p1, A)
    r2 = sw.resolve_auto_pay(p2, A)
    r3 = sw.resolve_auto_pay(p3, A)
    print(f"{'✅' if r1 else '❌'} 配置齐全 → 自动付 {r1}")
    print(f"{'✅' if not r2 else '❌'} 没配观演人 → 不自动付 {r2}")
    print(f"{'✅' if not r3 else '❌'} 配置关闭 → 不自动付 {r3}")

    A.pay = True
    r4 = sw.resolve_auto_pay(p3, A)
    print(f"{'✅' if r4 else '❌'} --pay 强制开 → {r4}")
    return r1 and not r2 and not r3 and r4




def check_size_split():
    """区域/座位的分界必须跟着缩放走（踩过：固定 60px，缩到 392px 宽时区域全被判成座位）"""
    def mk(median, items):
        return {"medianSize": median, "available": [
            dict(x, available=True) for x in items]}

    normal = mk(70, [
        {"name": "A1区", "w": 90, "h": 70},
        {"name": "", "w": 14, "h": 14}])
    zoomed = mk(19, [
        {"name": "A1区", "w": 43, "h": 45},
        {"name": "", "w": 8, "h": 8}])
    seatmap = mk(0, [{"name": "", "w": 14, "h": 14}])

    a1 = sw.area_level(normal); s1 = sw.seat_level(normal)
    a2 = sw.area_level(zoomed);  s2 = sw.seat_level(zoomed)
    a3 = sw.area_level(seatmap); s3 = sw.seat_level(seatmap)

    ok1 = len(a1) == 1 and a1[0]["name"] == "A1区" and len(s1) == 1
    ok2 = len(a2) == 1 and a2[0]["name"] == "A1区" and len(s2) == 1
    ok3 = len(a3) == 0 and len(s3) == 1
    print(f"{'✅' if ok1 else '❌'} 常规尺寸 区域{len(a1)} 座位{len(s1)}")
    print(f"{'✅' if ok2 else '❌'} 缩放后(中位19px) 区域{len(a2)} 座位{len(s2)}")
    print(f"{'✅' if ok3 else '❌'} 纯座位图(无中位) 区域{len(a3)} 座位{len(s3)}")
    return ok1 and ok2 and ok3


def main():
    all_ok = True

    # 场景1：首选区域点进去没座位 → 刷新 → 同票档有座 → 锁座成功
    page = FakePage({
        "areas": [area("内场A1区"), area("内场A2区"), area("601区")],
        "seats": {"内场A2区": [seat(45)]},
    })
    all_ok &= run("首选被锁 → 同票档命中 → 锁座", page, project(),
                  True, ["内场A1区", "内场A2区"])

    # 场景2：首选 + 同票档全部落空 → 全场兜底
    page = FakePage({
        "areas": [area("内场A1区"), area("内场A2区"), area("601区")],
        "seats": {"601区": [seat(9)]},
    })
    all_ok &= run("内场全落空 → 全场兜底命中", page, project(),
                  True, ["内场A1区", "内场A2区", "601区"])

    # 场景3：座位号不在范围内 → 退回第一个可售（不能空手而归）
    page = FakePage({
        "areas": [area("内场A1区")],
        "seats": {"内场A1区": [seat(120)]},
    })
    all_ok &= run("座位号超范围 → 仍然锁（不空手）", page, project(seat_range=(1, 80)),
                  True, ["内场A1区"])

    # 场景4：全场都没座位 → 不锁，返回 False
    page = FakePage({
        "areas": [area("内场A1区"), area("内场A2区"), area("601区")],
        "seats": {},
    })
    all_ok &= run("全都没座 → 不乱点", page, project(), False,
                  ["内场A1区", "内场A2区", "601区"])

    # 场景5：首选区域就是唯一可售 → 一次命中
    page = FakePage({
        "areas": [area("内场A1区")],
        "seats": {"内场A1区": [seat(3)]},
    })
    all_ok &= run("首选直接命中", page, project(), True, ["内场A1区"])

    if not check_restock_areas():
        all_ok = False
    if not check_phase_rules():
        all_ok = False
    if not check_detect_phase():
        all_ok = False
    if not check_auto_pay_rules():
        all_ok = False
    if not check_size_split():
        all_ok = False

    print()
    print("全部通过" if all_ok else "有失败")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

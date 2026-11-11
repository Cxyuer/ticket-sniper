#!/usr/bin/env python3
"""同程旅行小程序(微信 PC 版) —— 余票监控 + 自动点进下单页

先要理解前置动作（不做这两步会一直失败）：
    1) raise_window: 宿主窗口常盖在最上层, 不提窗, 点击会打到别的 App
    2) 关弹窗: 切 tab / 进页面会弹「特别提醒」, 不关掉就挡住底部按钮

原理: 小程序无法代理抓包, 只能屏幕级轮询
    截图小程序窗口 → 采样底部主按钮 HSV 饱和度
    售罄态 #CDF7BE 饱和度约 23%, 有票态约 >45% → 饱和度突变即放票
    → 提窗 + 点击 → 进入下单页 → 四层提醒你去付款

用法:
    python3 ly_watch.py --calibrate     # 标定当前按钮颜色/阈值
    python3 ly_watch.py --dry-run       # 只检测不点击
    python3 ly_watch.py                 # 检测 + 自动点击

前置: 系统设置 → 隐私与安全性 → 辅助功能 + 屏幕录制, 均勾选运行脚本的宿主程序
"""

import argparse
import colorsys
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from common.config import load_config, make_logger
from common.notify import notify

log = make_logger("ts_tongcheng")

TOOLS = os.path.join(ROOT, "tools")
WINLIST = os.path.join(TOOLS, "winlist")
DOCLICK = os.path.join(TOOLS, "doclick")
AXRAISE = os.path.join(TOOLS, "axraise")
LOCKSTATE = os.path.join(TOOLS, "lockstate")

POPUP_ROWS = (1150, 1260)      # 「特别提醒」确认按钮所在行(2x 截图相对坐标)
CAP = "/tmp/ly_cap.png"
STATE = os.path.expanduser("~/.ts_tongcheng_state.json")


# ---------------- 屏幕与窗口 ----------------

def find_window(key):
    """返回 (windowId, x, y, w, h) 或 None"""
    try:
        out = subprocess.run([WINLIST], capture_output=True, timeout=10)
    except Exception:
        return None
    for line in out.stdout.decode("utf-8", "ignore").splitlines():
        p = line.split("|")
        if len(p) < 4 or key not in (p[1] + p[2]):
            continue
        try:
            g = p[3].split(",")
            wh = g[2].split("x")
            return (int(p[0]), float(g[0]), float(g[1]),
                    float(wh[0]), float(wh[1]))
        except Exception:
            continue
    return None


def raise_window(key):
    subprocess.run([AXRAISE, key], capture_output=True, timeout=10)


def is_locked():
    """锁屏后窗口不再重绘, 截图是旧帧 → 监控静默失效, 必须报出来"""
    try:
        out = subprocess.run([LOCKSTATE], capture_output=True, timeout=5)
        return out.stdout.decode().strip() == "LOCKED"
    except Exception:
        return False


def capture(wid):
    subprocess.run(["screencapture", "-l", str(wid), "-x", "-o", CAP],
                   capture_output=True, timeout=15)
    return os.path.exists(CAP) and os.path.getsize(CAP) > 1000


def click(x, y):
    return subprocess.run([DOCLICK, str(int(x)), str(int(y))],
                          capture_output=True, timeout=10).returncode == 0


# ---------------- 像素判定 ----------------

def _is_pale_green(r, g, b):
    rr, gg, bb = [v / 255 for v in (r, g, b)]
    _, s, v = colorsys.rgb_to_hsv(rr, gg, bb)
    return v > 0.85 and 0.08 < s < 0.45 and g > r + 8 and g > b + 8


def scan_row(y_from, y_to, base_w):
    """在行区间里找最宽的浅绿长条 → (宽度, (中心x, y))"""
    from PIL import Image
    im = Image.open(CAP).convert("RGB")
    W, H = im.size
    k = W / base_w
    best_w, best_pos = 0, None
    for y in range(int(y_from * k), min(int(y_to * k), H), max(2, int(8 * k))):
        run, start = 0, None
        for x in range(0, W, 4):
            if _is_pale_green(*im.getpixel((x, y))):
                run += 4
                if start is None:
                    start = x
                if run > best_w:
                    best_w, best_pos = run, (start + run / 2, y)
            else:
                run, start = 0, None
    return best_w, best_pos


def btn_metrics(cfg):
    """底部主按钮的平均色与 HSV → (hex, s, v)"""
    from PIL import Image
    im = Image.open(CAP).convert("RGB")
    W, H = im.size
    k = W / float(cfg.get("base_width", 828))
    x1, y1, x2, y2 = [int(v * k) for v in cfg["button_rel"]]
    crop = im.crop((x1, y1, min(x2, W - 1), min(y2, H - 1)))
    px = list(crop.resize((60, 10)).getdata())
    row = px[60 * 4:60 * 5] or px
    avg = tuple(sum(c[i] for c in row) // len(row) for i in range(3))
    _, s, v = colorsys.rgb_to_hsv(*[v / 255 for v in avg])
    return "#%02X%02X%02X" % avg, s, v


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--saturation", type=float, default=0)
    args = ap.parse_args()

    cfg = load_config().get("tongcheng", {})
    key = cfg.get("window_key", "同程旅行")
    base_w = float(cfg.get("base_width", 828))
    sat = args.saturation or float(cfg.get("saturation", 0.45))
    interval = args.interval or float(cfg.get("interval", 4))

    win = find_window(key)
    if not win:
        log(f"❌ 没找到「{key}」窗口 —— 先在微信里打开小程序并停在演出详情页")
        return 1
    log(f"窗口 id={win[0]} 位置=({win[1]:.0f},{win[2]:.0f}) "
        f"尺寸={win[3]:.0f}x{win[4]:.0f}")

    if not capture(win[0]):
        log("❌ 截图失败, 检查「屏幕录制」权限")
        return 1

    if args.calibrate:
        hexc, s, v = btn_metrics(cfg)
        log(f"主按钮 {hexc} S={s*100:.0f}% V={v*100:.0f}%")
        log("判定: " + ("🟢 可购买" if s > sat and v > 0.4 else "⚪ 售罄/禁用"))
        pw, pos = scan_row(*POPUP_ROWS, base_w)
        log(f"弹窗: {'有' if pw > 300 else '无'} (浅绿条 {pw}px)")
        return 0

    log(f"开始监控 | 间隔 {interval:g}s | 阈值 S>{sat*100:.0f}% | "
        f"{'仅检测' if args.dry_run else '自动点击'}")

    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    clicked_at = state.get("clicked_at", 0)
    last = None
    popup_hits = 0
    last_beat = 0          # 只在状态长期不变时也留一行，便于判断是否卡死

    while True:
        win = find_window(key)
        if not win:
            log("⚠️ 小程序窗口不见了, 等待…")
            time.sleep(interval * 3)
            continue
        wid, wx, wy, ww, wh = win

        if is_locked():
            if not state.get("warned_locked"):
                log("🔒 屏幕已锁定! 界面停止刷新, 监控暂时失效")
                log("   → 系统设置 → 锁定屏幕 → 设为「永不」, 并关闭屏保")
                notify("监控已失效", "屏幕锁定导致界面不刷新, 请解锁并关闭自动锁屏")
                state["warned_locked"] = True
                json.dump(state, open(STATE, "w"))
            time.sleep(max(interval, 10))
            continue
        if state.get("warned_locked"):
            log("🔓 屏幕已解锁, 监控恢复")
            state.pop("warned_locked", None)
            json.dump(state, open(STATE, "w"))

        if not capture(wid):
            time.sleep(interval)
            continue

        # 1) 弹窗优先（挡住按钮就没法判定）
        pw, pos = scan_row(*POPUP_ROWS, base_w)
        if pw > 300 and pos:
            popup_hits += 1
            if popup_hits <= 3:
                log("检测到「特别提醒」弹窗 → 自动关闭")
            if not args.dry_run:
                raise_window(key)
                click(wx + pos[0], wy + pos[1])
                time.sleep(1.2)
            continue
        popup_hits = 0

        # 2) 主按钮
        try:
            hexc, s, v = btn_metrics(cfg)
        except Exception:
            time.sleep(interval)
            continue

        enabled = s > sat and v > 0.4
        if hexc != last:
            log(f"主按钮 {hexc} S={s*100:.0f}% → "
                f"{'🟢 可购买' if enabled else '⚪ 售罄'}")
            last = hexc

        # 每 5 分钟留一次心跳，否则售罄期间日志长期不动，看不出是死是活
        if time.time() - last_beat > 300:
            log(f"❤️ 心跳 | 按钮 {hexc} S={s * 100:.0f}% | 弹窗 {popup_hits}")
            last_beat = time.time()

        if enabled and (time.time() - clicked_at) > 90:
            ax = wx + (cfg["button_rel"][0] + cfg["button_rel"][2]) / 4.0
            ay = wy + (cfg["button_rel"][1] + cfg["button_rel"][3]) / 4.0
            log(f"🟢 检测到可购买! 点击 ({ax:.0f},{ay:.0f})")
            if args.dry_run:
                notify("同程 双日通票(仅检测)", "检测到可购买状态, 未点击")
            else:
                raise_window(key)
                time.sleep(0.8)
                ok = click(ax, ay)
                log(f"点击结果: {ok}")
                clicked_at = time.time()
                state["clicked_at"] = clicked_at
                json.dump(state, open(STATE, "w"))
                if ok:
                    time.sleep(1.5)
                    subprocess.run(["screencapture", "-l", str(wid), "-x", "-o",
                                    "/tmp/ly_after_click.png"], capture_output=True)
                    notify("同程 双日通票",
                           "已自动点进下单页, 请立即选票档并支付!")

        time.sleep(interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("已停止")

#!/usr/bin/env bash
# 多项目抢票的起停脚本
#
#   ./run.sh projects             列出 config 里的项目
#   ./run.sh start                启动所有项目的猫眼两路 + 同程一路
#   ./run.sh start <项目>          只启动该项目
#   ./run.sh start <项目> seat     只启动该项目的座位监控
#   ./run.sh stop [项目]           停（不传项目=全停）
#   ./run.sh status               看谁在跑 + 是否锁屏
#   ./run.sh logs [项目]           跟踪日志
#   ./run.sh login [项目]          Playwright 后端首次登录（弹窗人工登录一次）
#   ./run.sh backend              当前用的是哪个浏览器后端
#
# 通道说明:
#   seat       座位图监控 + 分级抢座（需浏览器 tab，自动发现）
#   api        票档接口监控（锁屏也活着，兜底）
#   tongcheng  同程小程序窗口监控（全局一路，不分项目）
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY=python3

# 固定 CDN/风控参数无关，这里只要求 python3 可用
command -v $PY >/dev/null || { echo "找不到 python3"; exit 1; }

# 防休眠：mac 用 caffeinate；其他 unix 没有就用空（Windows 请用 run.ps1）
KEEP=""
command -v caffeinate >/dev/null && KEEP="caffeinate -d -i -s"

# 日志最后修改时间（mac 的 stat -f 和 Linux 的 stat -c 不通用，直接问 python）
mtime() {
  $PY -c 'import os,sys;print(int(os.path.getmtime(sys.argv[1])))' "$1" 2>/dev/null || echo 0
}

LOG_TONGCHENG=/tmp/ts_tongcheng.out

started_any=0

start_seat() {
  local proj="$1"
  local pid=$(python3 -c "import sys;sys.path.insert(0,'.');from common.config import load_project;print(load_project('$proj')['performance_id'])" 2>/dev/null)
  [ -z "$pid" ] && { echo "  seat      : 跳过（项目 $proj 无 performance_id）"; return; }

  if pgrep -f "seat_watch.py --project $proj" >/dev/null; then
    echo "  seat      : 已在跑"; return
  fi

  local tab=$(python3 tools/find_tab.py "$pid" 2>/dev/null)
  if [ -z "$tab" ]; then
    echo "  seat      : ⚠️ 没找到座位页 tab —— 先在浏览器打开"
    echo "              https://show.maoyan.com/myshowfe/trade/seat?id=$pid&sId=$(python3 -c "import sys;sys.path.insert(0,'.');from common.config import load_project;print(load_project('$proj')['show_id'])")"
    return
  fi

  nohup $KEEP $PY maoyan/desktop/seat_watch.py \
        --project "$proj" --tab "$tab" > "/tmp/ts_${proj}_seat.out" 2>&1 &
  echo "  seat      : 已启动 tab=$tab → /tmp/ts_${proj}_seat.out"
  started_any=1
}

start_api() {
  local proj="$1"
  if pgrep -f "api_watch.py --project $proj" >/dev/null; then
    echo "  api       : 已在跑"; return
  fi
  nohup $KEEP $PY maoyan/desktop/api_watch.py --project "$proj" \
        > "/tmp/ts_${proj}_api.out" 2>&1 &
  echo "  api       : 已启动 → /tmp/ts_${proj}_api.out"
  started_any=1
}

start_tongcheng() {
  if pgrep -f "ly_watch.py" >/dev/null; then
    echo "  tongcheng : 已在跑"; return
  fi
  nohup $KEEP $PY tongcheng/desktop/ly_watch.py \
        > "$LOG_TONGCHENG" 2>&1 &
  echo "  tongcheng : 已启动 → $LOG_TONGCHENG"
  started_any=1
}

PROJECTS=$(python3 maoyan/desktop/api_watch.py --list 2>/dev/null)

cmd="${1:-status}"
arg2="${2:-}"
arg3="${3:-}"

case "$cmd" in
  projects)
    echo "$PROJECTS" ;;

  start)
    if [ -n "$arg2" ]; then
      echo "$PROJECTS" | grep -qx "$arg2" || { echo "没有项目「$arg2」，可选: $(echo $PROJECTS)"; exit 1; }
      targets="$arg2"
    else
      targets="$PROJECTS"
    fi

    for proj in $targets; do
      echo "[$proj]"
      if [ "$arg3" = seat ] || [ -z "$arg3" ]; then start_seat "$proj"; fi
      if [ "$arg3" = api ]  || [ -z "$arg3" ]; then start_api  "$proj"; fi
      # 同程是全局窗口，只在全量启动时带一次
      if [ -z "$arg3" ]; then start_tongcheng; fi
    done
    [ "$started_any" = 0 ] && echo "（没有新启动的进程）"
    ;;

  stop)
    if [ -n "$arg2" ]; then
      pkill -f "seat_watch.py --project $arg2" && echo "  [$arg2] seat 已停"
      pkill -f "api_watch.py --project $arg2"  && echo "  [$arg2] api 已停"
    else
      pkill -f "seat_watch.py" && echo "  seat 已停"
      pkill -f "api_watch.py"  && echo "  api 已停"
      pkill -f "ly_watch.py"   && echo "  tongcheng 已停"
      [ -n "$KEEP" ] && pkill -f "caffeinate -d -i -s" 2>/dev/null && echo "  caffeinate 已停"
    fi
    exit 0 ;;

  status)
    now=$(date +%s)
    fresh() {   # 日志 $1 秒内有更新 → 活着
      local f="$1" limit="${2:-180}"
      [ -f "$f" ] || { echo "⚪"; return; }
      local age=$(( now - $(mtime "$f") ))
      if [ "$age" -le "$limit" ]; then echo "✅"; else echo "⚠️${age}s未更新"; fi
    }
    for proj in $PROJECTS; do
      n1=$(pgrep -f "seat_watch.py --project $proj" | wc -l | tr -d ' ')
      n2=$(pgrep -f "api_watch.py --project $proj"  | wc -l | tr -d ' ')
      a1="⚪"; [ "$n1" -gt 0 ] && a1="$(fresh /tmp/ts_${proj}_seat.out 240)"
      a2="⚪"; [ "$n2" -gt 0 ] && a2="$(fresh /tmp/ts_${proj}_api.out 120)"
      echo "  [$proj] seat:$a1 api:$a2"
    done
    n3=$(pgrep -f "ly_watch.py" | wc -l | tr -d ' ')
    a3="⚪"; [ "$n3" -gt 0 ] && a3="$(fresh /tmp/ts_tongcheng.out 400)"
    echo "  [同程]   $a3"
    lock=""
    [ -x ./tools/lockstate ] && [ "$(uname -s)" = "Darwin" ] && lock=$(./tools/lockstate 2>/dev/null)
    echo "  屏幕: ${lock:-未知}"
    ;;

  backend)
    python3 -c "import sys;sys.path.insert(0,'.');import common.browser as b;print('后端:',b.backend_name())" ;;

  login)
    proj="${arg2:-$(echo $PROJECTS | awk '{print $1}')}"
    $PY tools/open_browser.py --project "$proj" --login ;;

  logs)
    if [ -n "$arg2" ]; then
      tail -f "/tmp/ts_${arg2}_seat.out" "/tmp/ts_${arg2}_api.out" 2>/dev/null
    else
      tail -f /tmp/ts_*_seat.out /tmp/ts_*_api.out "$LOG_TONGCHENG" 2>/dev/null
    fi ;;

  *)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' ;;
esac

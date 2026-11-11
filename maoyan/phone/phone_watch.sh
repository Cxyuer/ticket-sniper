#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# 猫眼演出 —— 手机端兜底监控（Termux）
#
# 它只做一件事：票档接口出现余票时，立刻震动 + 高优先级通知 + 可选打开座位页。
# 手机上没有能力自动下单（不能注入点击），真正的选座/锁座在电脑端跑。
# 所以它不区分首发还是回流，只负责「有票就叫你」。
#
# 第一次用手机跑？看仓库 README「手机端 → 从零开始」，一共七步：
#   装 Termux + Termux:API（同来源）→ pkg install -y termux-api curl
#   → 给 Termux:API 通知权限、Termux 电池设为「无限制」
#   → curl 下载本脚本 → nano 改顶部 P/SID → bash phone_watch.sh
#
# 手机能力边界（均已实测，别再试）：
#   ✅ curl 查接口（原生 HTTP，无跨域）
#   ✅ termux-vibrate / termux-notification / termux-wake-lock / termux-open
#   ❌ am / cmd / dumpsys —— Permission Denial（Termux 不是 shell 身份）
#   ❌ 无法向浏览器注入点击
# ============================================================
#
# ---------------------------- 配置 ----------------------------
# 只需改这一段。两个 ID 从购票页 URL 里取：
#   https://show.maoyan.com/myshowfe/trade/seat?id=<演出ID>&sId=<场次ID>
#                                          ↑P              ↑SID
#
# 写法 ${VAR:-默认值}：文件里的值就是默认值，环境变量可以临时覆盖它
#   例：I=5 bash phone_watch.sh      → 间隔变 5 秒
#       MAXP=1500 bash phone_watch.sh → 最高价 1500
P=${P:-516710}              # 演出ID（必填）
SID=${SID:-3929685}         # 场次ID（必填）
NAME=${NAME:-演出票}         # 通知里显示的名字

I=${I:-8}                   # 轮询间隔（秒）。手机省电建议 8~10
OPEN=${OPEN:-1}             # 1=有票自动用浏览器打开座位页；0=只通知
MAXP=${MAXP:-0}             # 最高可接受票价；0=不限（超过这个价的票档不叫）
# -------------------------- 配置结束 --------------------------
#
# 用法：
#   bash phone_watch.sh                    # 按上面的配置跑
#   I=5 bash phone_watch.sh                # 临时改间隔
#   P=xxx SID=yyy bash phone_watch.sh      # 临时换演出（环境变量优先）
#
# 日志：$HOME/ts.log
# ============================================================

B="https://show.maoyan.com/maoyansh/myshow/ajax"
UA="Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
SEAT="https://show.maoyan.com/myshowfe/trade/seat?id=$P&sId=$SID"
LOG=$HOME/ts.log

# ---------------- 启动前检查：配置不对就别跑 ----------------
if [ -z "$P" ] || [ -z "$SID" ]; then
  cat <<'EOF'
❌ 没配演出ID/场次ID。

怎么拿：浏览器打开购票页，地址栏形如
  https://show.maoyan.com/myshowfe/trade/seat?id=516710&sId=3929685
                                              ↑id      ↑sId
把 id 填到脚本顶部的 P，sId 填到 SID，保存后重跑。

也可以临时传：
  P=516710 SID=3929685 bash phone_watch.sh
EOF
  exit 1
fi

echo "=========== 启动前确认 ==========="
echo "演出ID   $P"
echo "场次ID   $SID"
echo "名称     $NAME"
echo "轮询间隔 ${I}s"
echo "最高价   $([ "$MAXP" = 0 ] && echo '不限' || echo "¥$MAXP")"
echo "有票动作 $([ "$OPEN" = 1 ] && echo '通知 + 打开座位页' || echo '只通知')"
echo "日志     $LOG"
echo "---------------------------------"
echo "手机端只负责叫醒你，选座/锁座请在电脑端完成"
echo "=================================="

# ---------------- 能力自检 ----------------
termux-vibrate -d 300 >/dev/null 2>&1 && echo "震动     OK" || echo "震动     FAIL → pkg install termux-api"
termux-notification -t "监控启动" -c "$NAME" >/dev/null 2>&1 && echo "通知     OK" || echo "通知     FAIL → 检查 termux-api 权限"
termux-wake-lock 2>/dev/null && echo "唤醒锁   OK" || echo "唤醒锁   跳过"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$B/performance/$P/tickets")
echo "接口连通 $code $([ "$code" = "200" ] && echo '' || echo '← 非 200，检查网络/演出ID')"

n=1
while :; do
  f=$(mktemp)
  curl -sL --max-time 20 -H "User-Agent: $UA" -H "Referer: https://show.maoyan.com/" \
       "$B/performance/$P/tickets" > "$f"

  if ! grep -q ticketPrice "$f"; then
    echo "$(date +%H:%M:%S) 接口异常/限流" | tee -a "$LOG"
    rm -f "$f"; sleep "$I"; continue
  fi

  hit=""; out=""
  for r in $(sed 's/},{/} {/g' "$f" | tr ' ' '\n' | grep ticketPrice); do
    pr=$(echo "$r" | sed -n 's/.*"ticketPrice":\([0-9.]*\).*/\1/p')
    case "$pr" in ""|0|0.0|0.00|0.000|0.0000) continue;; esac   # 0 元是内部工作票位

    # 超过最高价的不叫（MAXP=0 表示不限）
    if [ "$MAXP" != 0 ]; then
      over=$(awk -v a="$pr" -v b="$MAXP" 'BEGIN{print (a>b)?1:0}')
      [ "$over" = 1 ] && continue
    fi

    if echo "$r" | grep -q '"hasInventory":true'; then
      out="$out Y$pr"; hit="$hit $pr"
    else out="$out N$pr"; fi
  done
  echo "$(date +%H:%M:%S)$out" | tee -a "$LOG"

  if [ -n "$hit" ] && [ "$n" -gt 1 ]; then
    echo "### 🟢 放票 $hit" | tee -a "$LOG"
    # 连续 8 轮约 24 秒，手机在口袋里也能感知
    for k in 1 2 3 4 5 6 7 8; do
      termux-vibrate -d 1500 2>/dev/null
      termux-notification \
        -t "🟢 $NAME 有票!" \
        -c "¥$hit 立即下单" \
        --priority high --vibrate 1200 --sound 2>/dev/null
      for snd in /system/media/audio/notifications/*.ogg; do
        [ -f "$snd" ] && termux-media-player play "$snd" 2>/dev/null && break
      done
      sleep 3
    done

    if [ "$OPEN" = 1 ]; then
      echo "  → 打开猫眼座位页"
      termux-open "$SEAT" 2>/dev/null
    fi

    sleep 60   # 避免重复轰炸
  fi

  rm -f "$f"; n=2; sleep "$I"
done

# ticket-sniper

猫眼 / 同程 演出票监控与自动抢座。**支持多个演出项目并行**，参数全在
[config.json](config.json)，不用改代码。

仓库里 `config.json` 的 `projects.example` 只是占位示例（`enabled: false`，
不会被启动）。**真实项目建议写在 `config.local.json`**，该文件已列入 `.gitignore`，
你的演出 ID、区域偏好不会进仓库。格式见下文「新增一个项目」。

## 抢座策略：三级降级，抢到就锁

抢票真正卡人的地方不是「发现放票」，而是**点进去座位已经被别人锁了**。
所以不盯死一个区域，按三级逐级放宽，每级失败就刷新页面重来：

| 级别 | 范围 | 座位号 |
|---|---|---|
| 1 `exact` | 只点配置的首选区域 | 须在 `seat_range` 内 |
| 2 `tier` | 同一票档的所有区域 | 须在 `seat_range` 内 |
| 3 `all` | 全场任意可售区域 | 不限 |

**票档怎么判定**：优先用 `target.tier_areas` 显式配置；没配就自学习——
区域有票时 fill 颜色就代表票档，同色的区域归为同一档，学到后存
`maoyan/desktop/tier_map.json`；还没学到就按名称前缀归组（`内场*` / `十年同行区*` /
`V看台` / `数字看台` …）。只有一种颜色时不算学到（否则「同票档」会退化成「全场」）。

**为什么敢激进**：锁座后不付款没有任何损失，订单超时自动取消。所以策略是
「先锁住，再叫人付款」，锁座环节不等确认、不犹豫，连点两次底部 CTA。

**防误点的硬约束**：底部按钮走白名单（`allow_cta`），并且黑名单优先
（`deny_cta` 含「缺货登记」「想看」「退票」…）。售罄页底部就是「缺货登记」，
点错等于登记缺货、抢票直接失败，所以这个白名单是必须的。

## 平台支持：macOS / Windows / 手机

业务逻辑（轮询、模式判定、选座、降级）是纯 Python，不分平台。差异只在启动脚本和提醒：

| 部分 | macOS | Windows | 说明 |
|---|---|---|---|
| `api_watch.py` | ✅ | ✅ | 零依赖，纯 HTTP |
| `seat_watch.py` | ✅ | ✅ | 需要浏览器后端，Windows 用 Playwright |
| `ly_watch.py`（同程） | ✅ | ❌ | 依赖 `screencapture` + Swift 辅助功能点击，mac 专属 |
| `phone_watch.sh` | ✅ | ✅ | Termux 手机端，只叫醒不下单 |
| `run.sh` | ✅ | — | Windows 用 `run.ps1` |
| `notify.py` | osascript | PowerShell 通知 + SAPI 语音 | 已做双实现 |

| 浏览器后端 | 平台 | 说明 |
|---|---|---|
| `cli` | 任选 | 交给任意外部浏览器 CLI，命令写在 `config.local.json`（不进仓库） |
| `playwright` | 全平台 | 内置实现，用系统 Chrome + 独立 profile，**Windows 上就走这个** |

```bash
./run.sh backend      # 看当前用的是哪个
```

- `cli` —— 交给任意外部浏览器 CLI（命令在 `config.local.json` 里配，不进仓库）
- `playwright` —— 内置实现，用系统 Chrome + 独立 profile

切到 playwright：

```bash
# 1) config.json 里 "browser": { "backend": "playwright" }
# 2) 首次登录一次（会弹出独立的 Chrome 窗口，不是你日常那个）
./run.sh login <项目>
# 3) 正常启动
./run.sh start <项目>
```

登录态存在 `config.browser.profile_dir`（默认 `~/.ticket-sniper/chrome-profile`），
之后所有脚本复用，不用反复登录。它用 `channel="chrome"` 直接调系统 Chrome，
不需要 `playwright install` 下载浏览器。

> 无头模式默认关闭。票务风控能识别 headless，实测本场页面在无头下也会跳登录，
> 所以 `headless` 保持 `false`。

### 把仓库带到别的机器

仓库是纯本地 git，没配 remote。要搬走任选一种：

```bash
git bundle create ticket-sniper.bundle --all      # 单个文件，拷走后在目标机 git clone
# 或者 rg 你的 Git 服务
git remote add origin <url> && git push -u origin master
```

目标机上只需 `python3 -m pip install playwright`（用系统 Chrome 时无需下载浏览器），
或者配一个外部浏览器 CLI 走 `cli` 后端。

### Windows 上怎么跑

Windows 不用 `run.sh`（bash + pgrep），用同功能的 [`run.ps1`](run.ps1)，走 Playwright 后端。
前提只有两个：Python 3.10+、装了 Chrome。

```powershell
git clone <仓库地址> ticket-sniper
cd ticket-sniper

python -m pip install playwright          # 只装 Python 包，不下载浏览器
# config.json 里确认 "browser": { "backend": "playwright" }

.\run.ps1 login kpl                       # 弹出独立的 Chrome，手动登录一次猫眼
.\run.ps1 start kpl                       # 启动座位监控 + 接口监控
.\run.ps1 status                          # 谁在跑、日志多久没更新
.\run.ps1 logs kpl                        # 跟踪日志（日志在 %TEMP%\ticket-sniper\）
.\run.ps1 stop                            # 全停
```

提示「禁止运行脚本」时用：

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 start kpl
```

几点和 mac 不一样的地方：

- **同程通道（`ly_watch.py`）不启动**。它靠 macOS 截屏和辅助功能点击，Windows 上没有对应实现。
- **防休眠**：没有 `caffeinate`。长时间盯票前先在「电源和电池」里把「接通电源时进入睡眠」设为「从不」，否则睡眠会掐掉浏览器。
- **提醒**：`notify.py` 已内置 Windows 分支（PowerShell 通知 + SAPI 语音 + 提示音），锁屏也会响。
- **日志**：在 `%TEMP%\ticket-sniper\`，不是 `/tmp`。
- 座位监控直接读页面，**不依赖截图**，所以锁屏后照常工作。

## 三条通道怎么分工

| 通道 | 信号源 | 能自动到哪一步 | 锁屏后 |
|---|---|---|---|
| `maoyan/desktop/seat_watch.py` | 座位图 SVG 颜色 | 点区域 → 点座位 → **锁座**，停在支付页 | ✅ 实测可用 |
| `maoyan/desktop/api_watch.py` | 票档接口 `hasInventory` | 只提醒 + 打开购票页 | ✅ **仍可用** |
| `tongcheng/desktop/ly_watch.py` | 小程序按钮色相 | **点进下单页**，后面手动 | ❌ 失效 |

三条最后都汇到同一个动作：**打开下单界面 + 叫你付款**。支付环节（密码/指纹）
永远得你自己点。

## 快速开始

```bash
cd ticket-sniper

./run.sh projects          # 列出项目
./run.sh status            # 谁在跑 + 屏幕是否锁定
./run.sh start             # 启动所有项目
./run.sh start <项目>       # 只启动这个项目
./run.sh start <项目> seat  # 只启动它的座位监控
./run.sh logs <项目>        # 跟踪日志
./run.sh stop <项目>
```

Windows 把 `./run.sh` 换成 `.\run.ps1`，参数完全一样（同程通道不启动），
详见上面「Windows 上怎么跑」。

座位监控需要浏览器 tab（座位页），`run.sh` / `run.ps1` 会按 `performance_id`
自动发现 tab，浏览器重启也不会失联；连续几轮找不到时还会自己把 webview 导航回座位页。

单独调试：

```bash
python3 maoyan/desktop/seat_watch.py --project <项目> --check      # 只看区域/可售/CTA
python3 maoyan/desktop/seat_watch.py --project <项目> --once       # 跑一轮
python3 maoyan/desktop/seat_watch.py --project <项目> --no-submit  # 选座但不锁
python3 maoyan/desktop/seat_watch.py --project <项目> --area 内场A2区  # 临时换首选区域
python3 maoyan/desktop/api_watch.py --project <项目> --once
python3 tongcheng/desktop/ly_watch.py --calibrate
python3 tools/rehearse_sale.py --project <项目>  # 首发模拟：到点只点「第一下」，不选座不下单
```

## 首发 vs 回流（自动判断）

两种场景的目标不一样，脚本按**现场状态**自动选，不用手工猜：

| 现场看到什么 | 判定 | 抢法 |
|---|---|---|
| 有可售区域 | 直接抢 | 按首选区域逐级放宽 |
| 出现「开售提醒 / 预约 / 即将开售 / 倒计时」 | **还没开票** | 等首发（到点按你的区域精准抢） |
| 全部票档「缺货登记」 | **已开票、售罄** | 抢回流，默认全场都可以 |

首发抢法（三级放宽）：首选区域 → 同票档区域 → 全场。
回流抢法：默认**全场任意**；你在 `restock.areas` 里指定了档位，就**只抢这些档位**，
没票就继续等——不会退回全场。

**两套配置互相独立**：`target.*` 只影响首发，`restock.*` 只影响回流。
首发配了「内场A1区」，不会让回流也只抢内场A1区；反过来，回流配了档位，也不影响首发。

```json
"target":  { "area": "内场A1区", "seat_range": [1, 80] },   // 首发
"restock": { "areas": [],       "seat_range": [] }          // 回流；areas 空 = 全场
```

**配置可以热加载**：脚本每轮会重读 config，改了立即生效，不用重启。
所以「首发没抢到，临时决定回流只抢某档位」直接改 `restock.areas` 保存即可。

两种自动切换条件（`auto` 模式下）：

- 开票时间已过 `restock.switch_after_minutes`（默认 5 分钟）还没抢到 → 转回流
- 首发时有票但抢失败 `restock.switch_after_miss`（默认 1 次）→ 立刻转回流

想强制某一种，配 `"mode": "first"` / `"restock"`，或命令行 `--mode` 覆盖。
**要等二次开票**（新的开售批次）就配 `mode: first` 并写上 `sale_time`。

## 两种座位图（实测差异）

2026-11-11 用真实有票的演出验证过，猫眼至少有两套座位图实现，**交互模型完全不同**：

| 类型 | 渲染 | 选择粒度 | 典型场景 | 本项目支持 |
|---|---|---|---|---|
| 分区图 | `<svg>` + `<path>` | 选**区域**（如「内场A1区」） | 体育馆演唱会、电竞、体育赛事 | ✅ |
| 座位图 | `<canvas>` 分块 + `#sdk-seat-container` 接收事件 | 选**具体座位**（如「13排112座」） | 剧场、音乐剧、脱口秀 | ✅ |

判定方式（`--check` 会打印）：

```js
document.querySelectorAll('svg path').length        // >0 → 分区图
document.querySelectorAll('canvas').length          // >0 且 svg=0 → 座位图
```

**注意**：canvas 座位图只认真实输入事件，`element.dispatchEvent(new MouseEvent(...))`
无效；必须走 CDP（`click --position-x/y`）点 `#sdk-seat-container`，坐标由读取
canvas 像素算出来。实现见 `js/seat_grid.js` + `seat_watch.py` 的 `grid_pick()`。

两种场馆可能是**混合**的：概览层用 SVG 画区域，点进去之后座位改用 canvas 画。
所以 `seat_watch` 的流程是：点区域 → 轮询等待（SVG 立刻有座位级元素；canvas 要
5~6 秒渲染）→ 有 SVG 座位就按 SVG 选，没有就读像素走 canvas。

**座位范围的生效方式不同**：canvas 图里点之前不知道座位号，所以是「点一下 →
从页面读回 `13排112座` → 不在范围内就再点一次取消 → 换下一个点位」。

## 自动支付与实名观演人

**观演人在启动前确认，运行中不再打断。** 配置写 `target.viewers`，脚本按名字勾选，
然后点「立即支付」锁座（付款密码仍需本人，脚本不会碰）。

```json
"target": {
  "viewers": ["某位观演人的名字"],
  "auto_pay": true
}
```

启动时会先打印一份确认清单，这就是你核对的机会：

```
==============================================
项目     <项目名> | ...
首选区域 内场A1区 | 座位号 [1, 80]
最高价   1976 | 数量 1
观演人   某位观演人的名字
自动支付 开：会选观演人并点「立即支付」锁座
↑ 以上为启动前确认项；运行中不会再询问
==============================================
```

安全约束（都是踩出来的）：

| 情况 | 行为 |
|---|---|
| `auto_pay: true` 但 `viewers` 为空 | **降级为只到确认页**，并报警 |
| 配置的名字在列表里找不到 | 拒绝执行，停在确认页，通知你处理 |
| 需要 N 位但只勾上 < N 位 | 拒绝执行 |
| `--no-submit` / `--pay` | 单次覆盖配置，用于模拟 / 强制走到支付 |

实测（2026-11-11 ¥28 场）：勾选观演人 → 点「立即支付」→ 跳 `mpay.meituan.com`
收银台，订单生成、座位锁定，停在支付方式选择页，全程未付款。

**注意**：点「立即支付」是真人级的别人付钱动作，按文本点击没用，必须点
`button.primary-btn-md`（页面里还有一个隐藏的重下单按钮，别点错）。

实测（2026-11-11）两份演出都卡在同一个地方：订单确认页要求**选择实名制观演人**
（已保存的身份证信息，脱敏显示）。脚本按白名单只会点到这一页为止，不会替你选人、
也不会点「立即支付」。

## CTA 文案不统一（踩过）

同一个座位页，不同场馆的底部按钮文案不一样：

| 阶段 | 可能文案 |
|---|---|
| 详情页 | 选座购票 / 立即购买 / 缺货登记 |
| 座位页未选座 | 请选择座位（class 带 `opc40`，禁用） |
| 座位页已选座 | 确认选座 / 提交 |
| 订单确认页 | 立即支付 / 提交订单 |

所以判定「能不能点」**不能看文案**，要看 class 有没有 `opc40`（见
`js/seat_cta.js`）。而能不能点**由白名单决定**：`safety.allow_cta` 里
**故意不含「立即支付」「提交订单」**——脚本只会走到订单确认页，付款必须本人点。

## 新增一个项目

在 [config.json](config.json) 的 `projects` 里加一段，`run.sh` 自动认：

```json
{
  "projects": {
    "周杰伦": {
      "name": "周杰伦演唱会",
      "platform": "maoyan",
      "performance_id": "<演出ID>",
      "show_id": "<场次ID>",
      "sale_time": "2026-12-01 12:00:00",
      "target": {
        "area": "内场A1区",
        "seat_range": [1, 80],
        "max_price": 2000,
        "quantity": 1
      }
    }
  }
}
```

两个 ID 从座位页 URL 取：`.../trade/seat?id=<演出ID>&sId=<场次ID>`。

`sale_time` 语义：**只有确实知道开票时间才填**，脚本会待机到那一刻再高频轮询；
售罄等回流票必须留空（留空 = 一直按正常频率跑）。

## 关键前提（不做就一定失败）

1. **屏幕别锁**，因为同程那一路靠截图。锁屏后窗口不再重绘，截图会拿到旧帧，
   监控静默失效。实测边界（2026-11-11）：
   - `seat_watch.py` 走浏览器内部求值，**锁屏照常工作**（实测锁屏下仍读到 158 个区域）
   - `api_watch.py` 纯 HTTP，锁屏不影响
   - `ly_watch.py` 靠 `screencapture`，**锁屏即冻结**
2. **辅助功能 + 屏幕录制** 都要勾运行脚本的宿主程序（同程那路需要提窗和点击）。
3. 猫眼座位页要在浏览器里**已登录**。
4. 微信要打开且不最小化，同程小程序停在演出详情页。

## 猫眼的两套页面，别搞混

| 链接 | 是什么 | 能下单 |
|---|---|---|
| `show.maoyan.com/detail/516710` | Next.js 展示站（格瓦拉），JS 里 0 个 order 接口 | ❌ |
| `show.maoyan.com/qqw/#/detail/516710` | 猫眼演出购票 H5，有 order / realName / prepay 全套 | ✅ |
| `show.maoyan.com/myshowfe/trade/seat?id=&sId=` | 座位图页（`seat_watch.py` 用的） | ✅ |

接口基址是猫眼自有域 `https://show.maoyan.com/maoyansh/myshow/ajax`（点评域
`m.dianping.com/myshow/ajax` 同一后台，已弃用）。**匿名可读**：
`/performance/{id};poi=false`、`/performance/{id}/tickets`、`/performance/{id}/shows`。
交易类接口（`/realName/*`、`/order/*`）需要 H5guard 风控签名，裸 fetch 一律
`{"code":403,"msg":"请先登录！"}`，所以抢票只能走页面操作。

座位页自己会请求 `/mysh/odea/show/seatChart`、`/seatStatus`，还拉一份 CDN 上
**zstd 压缩**的座位图 blob（`s0.pipi.cn/mediaplus/show_odea_seat/*.json`）。
票档→区域映射就藏在那份压缩数据里；重放接口会被风控挡（一次性参数 + 拥堵），
所以本项目改用「颜色自学习」这条路，不依赖接口。

## 手机端（Termux）

`maoyan/phone/phone_watch.sh`：兜底监控。只做 curl 查票 + 震动 + 高优先级通知 +
唤醒锁，**不区分首发/回流，也不能下单**（手机无法注入点击）——它只负责「有票就叫醒你」，
真正的选座锁座在电脑端跑。

### 从零开始（第一次用手机跑）

**第 1 步：装两个 App**

| App | 下载地址 | 选哪个文件 |
|---|---|---|
| **Termux** | https://github.com/termux/termux-app/releases （当前 v0.118.3） | `termux-app_v0.118.3+github-debug_arm64-v8a.apk`（绝大多数手机）；拿不准就下 `universal` |
| **Termux:API** | https://github.com/termux/termux-api/releases （当前 v0.53.0） | `termux-api-app_v0.53.0+github.debug.apk` |
| F-Droid 备选（能打开时最省事） | https://f-droid.org/packages/com.termux/<br>https://f-droid.org/packages/com.termux.api/ | 页面里直接点「安装」 |

⚠️ **两个 App 必须来自同一地方**（都从 GitHub 装，或都从 F-Droid 装）。
混着装签名不同，`termux-api` 命令会连不上宿主 App，表现就是「震动 FAIL / 通知 FAIL」。

⚠️ **不要用 Google Play 里的 Termux**：那个版本已停止更新，连 `pkg install` 都会失败。

装完打开 Termux，等它自动初始化完（出现 `~ $` 提示符）。

**第 2 步：装依赖**

```bash
pkg update -y && pkg upgrade -y
pkg install -y termux-api curl
```

**第 3 步：给权限（这步不做，通知不会响）**

- 系统设置 → 应用 → **Termux:API** → 权限 → 允许「通知」
- 系统设置 → 应用 → **Termux** → 电池 → 选「无限制 / 不优化」
  （各家叫法不同，小米叫「无限制」，华为叫「手动管理」全开）
- 部分机型还要在「最近任务」里给 Termux 加锁，防止被清理

**第 4 步：把脚本下载到手机**

```bash
mkdir -p ~/ticket && cd ~/ticket
curl -fLO https://raw.githubusercontent.com/Cxyuer/ticket-sniper/main/maoyan/phone/phone_watch.sh
```

如果 GitHub 打不开（国内网络常见），用备用方式：把 `phone_watch.sh` 通过微信/QQ
发给自己，手机上下载后：

```bash
cp /sdcard/Download/phone_watch.sh ~/ticket/
```

**第 5 步：填你的演出 ID**

```bash
pkg install -y nano
nano ~/ticket/phone_watch.sh
```

改顶部那几行（写法见下面「怎么配」），`Ctrl+O` 回车保存，`Ctrl+X` 退出。
不想改文件也可以运行时临时传：

```bash
P=<演出ID> SID=<场次ID> NAME="某场演出" bash ~/ticket/phone_watch.sh
```

**第 6 步：运行**

```bash
cd ~/ticket && bash phone_watch.sh
```

看到「启动前确认」清单 + 各项 `OK` + `接口连通 200` 就说明跑起来了，
之后每 `I` 秒打一行 `N776.00 N1076.00 ...`（N=无票，Y=有票）。

**第 7 步：让它别被系统杀掉（推荐）**

```bash
termux-wake-lock                                    # 阻止息屏休眠
nohup bash phone_watch.sh > ~/ts.out 2>&1 &         # 后台跑
tail -f ~/ts.out                                    # 看日志
```

停止：

```bash
pkill -f phone_watch.sh
```

**常见问题**

| 现象 | 原因 / 解决 |
|---|---|
| `震动 FAIL` / `通知 FAIL` | 没装 Termux:API，或没在系统里给它通知权限 |
| 跑一会儿就停 | 被系统省电策略杀了，按第 3 步设「无限制」，并 `termux-wake-lock` |
| `接口连通 000` | 手机网络问题，或演出 ID 填错 |
| 一直 `N` 没反应 | 正常，说明当前无票；有票会变成 `Y776.00` 并触发震动 |

### 怎么配

打开脚本，顶部就是配置块，直接改这几行：

```bash
P=${P:-<演出ID>}         # 演出ID（必填）
SID=${SID:-<场次ID>}     # 场次ID（必填）
NAME=${NAME:-演出票}     # 通知里显示的名字
I=${I:-8}               # 轮询间隔秒，手机省电建议 8~10
OPEN=${OPEN:-1}         # 1=有票自动开座位页；0=只通知
MAXP=${MAXP:-0}         # 最高可接受票价；0=不限
```

两个 ID 从购票页地址栏取：

```
https://show.maoyan.com/myshowfe/trade/seat?id=<演出ID>&sId=<场次ID>
                                            ↑P          ↑SID
```

`${VAR:-默认值}` 的写法表示**环境变量可以临时覆盖文件里的值**，不用改文件：

```bash
bash phone_watch.sh                    # 用文件里的配置
I=5 bash phone_watch.sh                # 临时 5 秒一轮
MAXP=1976 bash phone_watch.sh          # 临时只看 1976 以内的票档
P=xxx SID=yyy MAXP=500 bash phone_watch.sh   # 临时换一场
```

### 跑起来会先打印确认清单

```
=========== 启动前确认 ===========
演出ID   516710
场次ID   3929685
名称     演出票
轮询间隔 8s
最高价   不限
有票动作 通知 + 打开座位页
日志     /home/u0_a123/ts.log
---------------------------------
手机端只负责叫醒你，选座/锁座请在电脑端完成
==================================
震动     OK
通知     OK
唤醒锁   OK
接口连通 200
```

自检里任何一项 FAIL，脚本都会直接告诉你缺什么（例如 `pkg install termux-api`）。
没填 ID 时会打印取 ID 的方法并退出，不会空跑。


已知**不可用**，不要再试：
- `am` / `cmd` / `dumpsys` → `Permission Denial`（Termux 不是 shell 身份）
- `termux-open-url` 不解析 `intent://...;end` 语法
- 微信小程序不能代理抓包（微信不走系统代理，包目录空、MMKV 加密）

## 目录

```
config.json                 所有可调参数 + 项目列表
run.sh                      一键起停（多项目，macOS/Linux）
run.ps1                     同上，Windows / PowerShell 版
common/config.py            项目加载 / 日志 / 开票窗口 / 票档分组
common/notify.py            四层提醒（macOS osascript / Windows PowerShell）
common/browser.py           后端门面（cli / playwright）
maoyan/desktop/seat_watch.py    座位监控 + 三级抢座
maoyan/desktop/api_watch.py     接口监控（兜底，锁屏可用）
maoyan/desktop/js/              注入页面执行：区域探测 / CTA 探测 / 主按钮 / 坐标点击
maoyan/phone/phone_watch.sh       手机端监控
tongcheng/desktop/ly_watch.py   同程小程序窗口监控 + 自动点单
tests/sim_strategy.py       三级策略的离线仿真（改逻辑后先跑它）
tools/                      工具二进制 + Swift 源码 + find_tab.py（二进制是 macOS 专属）
```

## 验证策略改动

放票是随机的，没法按需复现，所以策略逻辑用假页面仿真回归：

```bash
python3 tests/sim_strategy.py
```

覆盖 5 个场景：首选被锁→同票档命中、内场全落空→全场兜底、座位号超范围、
全都无座不乱点、首选直接命中。

## tools/ 说明

| 工具 | 作用 |
|---|---|
| `winlist` | 列窗口 `id\|app\|title\|x,y,WxH`，改 `window_key` 前用它查 |
| `axraise` | 按标题提窗到前台（不提窗点击会打到别的 App） |
| `doclick` | 屏幕绝对坐标点击，需辅助功能 |
| `lockstate` | 输出 `LOCKED` / `UNLOCKED` |
| `find_tab.py` | 按 URL 关键字查浏览器 tab id |

源码在 [tools/src/](tools/src/)。`tools/` 里的二进制是已授权的那份——
TCC 权限（辅助功能/屏幕录制）绑定在具体二进制上，**重新编译会丢权限**，
要重编就编到别处再手动重新授权。

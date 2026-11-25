# 早鸟工作台（Early Bird Workbench）

六领域早期信号雷达 + 每日聚合工作台。捕捉尚未被市场充分定价、但已具备扩散潜力的早期节点，
以可核验的 high 信源标准固化为每日日报，再聚合渲染为统一工作台页面。

## 这个智能体能做什么

- **六领域错峰追踪**：科技、医学、金融、消费、商业、人才，每个领域一套独立的纳入/排除范围、聚焦方向与分级信源清单。
- **强制信源校验**：每个事件组必须满足 ≥3 个独立主域名，且 Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2；`confidence=low`、来源或时间不确定的事件一律不得提交。校验由脚本执行，不通过则流程状态不前进。
- **四步 briefing 流程**：B1 候选检索 → B2 筛选与信源校验 → B3 日报撰写 → B4 终检归档，状态机 `INIT → B1_DONE → B2_DONE → B3_DONE → DONE`。
- **空结果静默**：某领域当日无合格信号时，终态为 `EMPTY_SILENT`，仍产出空结果日报供聚合器读取，但对用户 no_reply，不输出凑数内容。
- **聚合工作台**：读取六领域最新日报，渲染 `index.html`（KPI 概览 + 领域卡片 + 逐领域日报全文 + 信源统计），并保存每日快照 `daily/YYYY-MM-DD.html`。
- **失败保护**：聚合渲染或写入异常时，`index.html` 保持上一次的有效内容（原子写入，绝不清空），错误追加写入 `aggregate.log`。
- **兼容原日程提示词**：可直接粘贴原 Coze 版日程提示词，路径与技能调用会自动映射到本项目。

## 主要输入

| 输入 | 说明 |
| --- | --- |
| 日程触发提示词 | 7 条，见 `early_bird/SCHEDULE_PROMPTS.md`，可直接粘贴使用 |
| `setup_token` | 领域标识，也接受英文 slug（`tech`/`med`/`fin`/`consumer`/`biz`/`talent`）或中文名 |
| 联网检索结果 | 由 `web_search` 工具获取，作为 B1 候选来源 |
| 追踪契约 | `early_bird/tracking_contract_v2.json`，定义领域范围、信源分级与流程规则 |

## 主要输出

| 产物 | 路径 |
| --- | --- |
| 候选信号清单（B1） | `early_bird/热点资讯追踪/早鸟雷达-{领域}/raw_candidates.json` |
| 合格事件清单（B2） | `early_bird/热点资讯追踪/早鸟雷达-{领域}/event_list.json` |
| 日报正文（B3） | `early_bird/热点资讯追踪/早鸟雷达-{领域}/daily/YYYY-MM-DD.md` |
| 结构化摘要（B3） | `early_bird/热点资讯追踪/早鸟雷达-{领域}/summary.json` |
| 流程状态机 | `early_bird/热点资讯追踪/早鸟雷达-{领域}/state.json` |
| 当日归档副本（B4） | `early_bird/热点资讯追踪/早鸟雷达-{领域}/daily/YYYY-MM-DD/` |
| 聚合工作台 | `early_bird/工作台/index.html` |
| 每日快照 | `early_bird/工作台/daily/YYYY-MM-DD.html` |
| 聚合清单 | `early_bird/工作台/manifest.json` |
| 聚合日志 | `early_bird/aggregate.log` |

## 配置的工具与脚本

### 智能体工具（`src/tools/early_bird.py`）

| 工具 | action | 用途 |
| --- | --- | --- |
| `early_bird_briefing` | `init` | 初始化某领域某日流程，返回完整领域契约与首步指引 |
| | `next` | 查看下一步指引 |
| | `submit` | 提交并校验某步产物（B1/B2/B3/B4） |
| | `status` | 查看流程状态 |
| | `list` | 列出六领域 token、时刻表与今日状态 |
| `early_bird_aggregate` | `snapshot` | 聚合六领域日报，渲染 index.html 与每日快照 |
| | `status` | 查看各领域采集状态与工作台产物 |
| | `domains` | 列出六领域目录与最新日报日期 |

工具是脚本的薄封装，校验规则与 CLI 完全一致（共用 `early_bird/common.py`）。

### 脚本（`early_bird/`）

| 文件 | 说明 |
| --- | --- |
| `tracking_contract_v2.json` | 六领域追踪契约，唯一事实来源 |
| `common.py` | 契约加载、路径解析、状态机、high 信源校验、按日归档读取 |
| `guide.py` | briefing 流程引导与逐步校验 CLI |
| `aggregate.py` | 工作台聚合渲染 CLI（含轻量 Markdown→HTML 渲染，无第三方依赖） |
| `selftest.py` | 端到端自检（85 项断言，在临时目录运行，不污染项目） |
| `SCHEDULE_PROMPTS.md` | 7 条可直接粘贴的调度提示词与路径映射表 |

### 复用的模板内置能力

- `web_search`：B1 候选检索（支持 `freshness` 时间窗）
- `preview_file` / `preview_folder`：预览工作台页面与产物目录

### 已配置的社区技能（`skills/`）

三个检索与核实技能，用于增强 B1 覆盖度与 B2/B3 核实强度。**它们不改变 high 信源硬规则**——无论候选来自哪个技能，最终都必须由 `early_bird_briefing` 的脚本校验通过才算合格。

| 技能 | 接入环节 | 作用 |
| --- | --- | --- |
| `find-news`（查找资料） | B1 | 多引擎搜索（Google/Baidu/Bing/DuckDuckGo/Yahoo）+ 微信公众号/GitHub/Reddit/Bilibili 垂类；`crawl_results>0` 取回原文核实发布时间与引文 |
| `multi-source-research`（多源研究） | B1+B2 | 整合网页/学术/社交/新闻聚合，自动去重并按可信度分级；辅助转载聚类与独立域名判定 |
| `research-orchestrator`（深度研究） | B2+B3 | 多源交叉验证、可信度评估与冲突检测；域名数卡线或来源冲突时深度核实 |

可信度分级映射：A 级（官方/政府/核心期刊）→ `tier1`；B 级（主流媒体）→ `tier2`（须在契约清单内）；C 级（自媒体/社交）→ `unknown`（不得单独支撑事件组）。

## 调度时刻表

| 链条 | 时间 | setup_token | 执行内容 |
| --- | --- | --- | --- |
| 科技 | 08:03 | `setup_0da2e5ce` | briefing B1→B4 |
| 医学 | 08:16 | `setup_244e21da` | briefing B1→B4 |
| 金融 | 08:29 | `setup_ccbd5295` | briefing B1→B4 |
| 消费 | 08:42 | `setup_63c56ee9` | briefing B1→B4 |
| 商业 | 08:55 | `setup_d93a5b44` | briefing B1→B4 |
| 人才 | 09:08 | `setup_26010b88` | briefing B1→B4 |
| 聚合 | 09:45 | — | `snapshot` → index.html + daily/ |

## 示例请求

**示例 1：跑单个领域**

> 跑一下科技领域的早鸟雷达

智能体会执行 `early_bird_briefing(action="init", setup_token="setup_0da2e5ce")`，
按 B1→B4 完成检索、校验、日报撰写与归档，最后只回报状态、事件数与产物路径。

**示例 2：查看全局状态**

> 六个领域今天都出报了吗

智能体会执行 `early_bird_aggregate(action="status")`，简报各领域日报日期、流程状态、
事件数、信源统计与待处理告警。

**示例 3：刷新工作台**

> 重新聚合渲染工作台

智能体会执行 `early_bird_aggregate(action="snapshot")`，渲染 `index.html`
与当日快照，并简报 KPI；失败时保留上一次结果并指向 `aggregate.log`。

**示例 4：粘贴原日程提示词**

> ```text
> 扣子话题追踪 - 「早鸟雷达-科技」
> 2. 执行命令：python "/Coze/Drive/编程专家/.skills/skill_topic_tracking/scripts/guide.py" init --flow briefing --setup-token "setup_0da2e5ce"
> 4. 产物统一写入：/Coze/Drive/编程专家/热点资讯追踪/早鸟雷达-科技/
> ```

智能体会识别原 Coze 提示词，把路径映射到 `early_bird/热点资讯追踪/早鸟雷达-科技/`，
把 `guide.py` 调用映射为 `early_bird_briefing`，其余流程要求逐条照办。

## 自动化与邮件推送

### 常驻调度器（`src/early_bird_scheduler.py`）

随模板服务启动，无需外部日程平台：

- 每 20 秒 tick 一次（`EARLY_BIRD_SCHEDULER_TICK_SECONDS` 可调），按 `tracking_contract_v2.json` 的 schedule 到点驱动对应领域链；
- 领域链在进程内直接驱动智能体（独立 thread_id，不污染用户会话），完整回复存 `early_bird/工作台/runs/<date>/<slug>.log`；
- 聚合链完成后自动触发邮件推送；
- 服务重启后默认补跑当日已错过的任务（`EARLY_BIRD_CATCHUP=true`）；每条链每日最多 3 次尝试，状态存 `early_bird/scheduler_state.json`；
- 调度日志：`early_bird/scheduler.log`。

**独立守护进程（`early_bird/scheduler_daemon.py`）**：模板服务进程若未重启（旧代码无调度循环），
可单独启动守护进程让自动化立即生效：

```bash
setsid nohup python early_bird/scheduler_daemon.py >> early_bird/daemon.out 2>&1 &
kill $(cat early_bird/scheduler.lock)   # 停止
```

守护进程与模板服务内的调度循环通过 `early_bird/scheduler.lock`（flock）互斥：
同一时刻只有一个实例真正运行，另一个待命；持有者崩溃时内核释放锁，待命方在下一个 tick 自动接管。

### 邮件推送（`early_bird/notify.py`）

- 凭据：`config/credentials.env`（600 权限，已 gitignore；模板见 `credentials_template.env`）。代码只从环境/该文件读取，绝不硬编码授权码。
- 摘要三档：`concise`（精简，默认）/ `full`（含摘要、信号价值、来源清单）/ `notice`（仅提醒）。
- 空结果策略：`per_domain`（默认，逐领域报"无合格信号"）/ `all_empty` / `silent`。
- 发送失败不丢消息：进入 `early_bird/push_queue.json`，按间隔重试（默认 15 分钟），超限标记 `exhausted` 并保留；调度器每个 tick 顺带重试。
- 站内收件箱：无论邮件是否发出，摘要都写入 `early_bird/工作台/inbox/<date>.json` 与 `latest.json`。

### HTTP 接口（前缀 `/api/user/agent/early-bird`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/status` | 调度开关、时刻表、今日任务状态、手动队列、推送配置（不含授权码） |
| POST | `/run` | 手动触发某链：`{"chain":"tech|med|fin|consumer|biz|talent|aggregate","date":"YYYY-MM-DD","push":false}` |
| POST | `/push` | 立即推送某日摘要：`{"date":...,"mode":"concise|full|notice","force":false}` |
| POST | `/push/test` | 发送测试邮件，验证凭据与网络 |
| GET | `/push/retry` | 重试失败队列（`?force=true` 忽略间隔） |
| GET | `/inbox` | 查收件箱（`?date=YYYY-MM-DD`，默认最新） |

### CLI

```bash
python early_bird/notify.py status                       # 推送配置与队列状态
python early_bird/notify.py digest --date 2026-11-07     # 只构建摘要并写收件箱
python early_bird/notify.py digest --date 2026-11-07 --send   # 构建并发送
python early_bird/notify.py retry                        # 重试失败队列
python early_bird/notify.py test                         # 测试邮件
python early_bird/selftest_notify.py                     # 推送模块自检
```

### 网络与代理说明

SMTP 发送按以下顺序尝试，任一成功即发送：

1. **直连** `smtp.qq.com:465`（SSL）；
2. **代理 CONNECT 隧道**：依次尝试 `QQ_SMTP_PROXY`（显式配置）→ `https_proxy` → `http_proxy`，
   经代理建立到 SMTP 端口的隧道后完成 SSL 握手与登录。当前沙箱直连不可达，实际走第 2 条路径。

若三条路径均不可达，邮件进入重试队列等待网络恢复；摘要始终可在站内收件箱查看。

## 本地运行

```bash
# 列出六领域与今日状态
python early_bird/guide.py list

# 初始化并跑完某领域某日流程
python early_bird/guide.py init   --setup-token setup_0da2e5ce --date 2026-11-07
python early_bird/guide.py next   --setup-token setup_0da2e5ce --date 2026-11-07
python early_bird/guide.py submit --setup-token setup_0da2e5ce --step B1 --date 2026-11-07
# ... B2 / B3 / B4 同理

# 聚合渲染工作台
python early_bird/aggregate.py snapshot --date 2026-11-07
python early_bird/aggregate.py status   --date 2026-11-07

# 端到端自检（修改契约或脚本后必跑）
python early_bird/selftest.py
```

脚本仅使用 Python 标准库，无需额外依赖。

## 修改追踪设定

编辑 `early_bird/tracking_contract_v2.json` 即可调整领域定义、纳入/排除范围、聚焦方向、
信号类型、分级信源清单、检索种子、调度时间或 `setup_token`；
`global_rules` 控制 high 信源门槛（`min_independent_domains_per_event`）与空结果静默默认值。

改完运行 `python early_bird/selftest.py` 验证流程未被破坏。

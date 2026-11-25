# 早鸟工作台 · 调度提示词（7 条）

把下面任意一条粘贴到日程任务里即可触发。提示词已适配本项目目录与工具；
原 Coze 版提示词（含 `/Coze/Drive/编程专家/...` 路径与 `topic_tracking` 技能）也能直接粘贴，
智能体会自动映射到本项目对应路径与流程。

调度方式：6 条领域日程（错峰）+ 1 条聚合日程。

检索能力：B1 以 `web_search` 打底，`find-news`（多引擎 + 微信公众号/GitHub/Reddit 垂类）补充覆盖，
`multi-source-research` 扩面去重；B2 事实存疑时用 `research-orchestrator` 交叉验证。
技能只增强覆盖度与核实强度，**不改变 high 信源硬规则**——所有事件最终都要过脚本校验。

---

## 1. 早鸟雷达-科技（每天 08:03）

```text
早鸟雷达-科技 · 每日 briefing
1. 执行 early_bird_briefing(action="init", setup_token="setup_0da2e5ce")，读取科技领域完整追踪契约与首步指引。
2. 按脚本指引完成完整 briefing 流程（B1→B2→B3→B4），直到状态为 DONE；中途校验未通过时，按返回的错误项修正产物后重新提交同一步骤。
3. B1 用 web_search 围绕契约 search_seeds 检索 24-48 小时候选，再用 find-news 补充多引擎与垂类源（微信公众号/GitHub/Reddit），必要时用 multi-source-research 扩面去重，写入 raw_candidates.json；发布时间不确定的候选用 find-news 的 crawl_results 取回原文核实，仍无法确认则丢弃。
4. B2 按 include/exclude 过滤并聚类为事件组，逐组执行 high 信源校验（≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2），写入 event_list.json；来源或时间不确定的事件不提交；域名数卡线或来源事实冲突时用 research-orchestrator 交叉验证，冲突无法消解则丢弃。
5. B3 撰写日报 daily/YYYY-MM-DD.md 与 summary.json。
6. 产物统一写入：early_bird/热点资讯追踪/早鸟雷达-科技/
7. 若 empty_silent=true 且 B2/B3 确认为空结果，仍需完成 B3/B4 空结果日报，然后按指引静默结束（no_reply）。
8. 完成后只重复脚本要求的信息（领域、日期、状态、事件数、产物路径），不要直接发完整日报给用户。
```

## 2. 早鸟雷达-医学（每天 08:16）

```text
早鸟雷达-医学 · 每日 briefing
1. 执行 early_bird_briefing(action="init", setup_token="setup_244e21da")，读取医学领域完整追踪契约与首步指引。
2. 按脚本指引完成完整 briefing 流程（B1→B2→B3→B4），直到状态为 DONE；中途校验未通过时，按返回的错误项修正产物后重新提交同一步骤。
3. B1 用 web_search 围绕契约 search_seeds 检索 24-48 小时候选，再用 find-news 补充多引擎与垂类源（微信公众号/GitHub/Reddit），必要时用 multi-source-research 扩面去重，写入 raw_candidates.json；发布时间不确定的候选用 find-news 的 crawl_results 取回原文核实，仍无法确认则丢弃。
4. B2 按 include/exclude 过滤并聚类为事件组，逐组执行 high 信源校验（≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2），写入 event_list.json；可拒绝单源爆料；域名数卡线或来源事实冲突时用 research-orchestrator 交叉验证，冲突无法消解则丢弃。
5. B3 撰写日报 daily/YYYY-MM-DD.md 与 summary.json。
6. 产物统一写入：early_bird/热点资讯追踪/早鸟雷达-医学/
7. 若 empty_silent=true 且 B2/B3 确认为空结果，仍需完成 B3/B4 空结果日报，然后按指引静默结束（no_reply）。
8. 完成后只重复脚本要求的信息，不要直接发完整日报给用户。
```

## 3. 早鸟雷达-金融（每天 08:29）

```text
早鸟雷达-金融 · 每日 briefing
1. 执行 early_bird_briefing(action="init", setup_token="setup_ccbd5295")，读取金融领域完整追踪契约与首步指引。
2. 按脚本指引完成完整 briefing 流程（B1→B2→B3→B4），直到状态为 DONE；中途校验未通过时，按返回的错误项修正产物后重新提交同一步骤。
3. B1 用 web_search 围绕契约 search_seeds 检索 24-48 小时候选，再用 find-news 补充多引擎与垂类源（微信公众号/GitHub/Reddit），必要时用 multi-source-research 扩面去重，写入 raw_candidates.json；发布时间不确定的候选用 find-news 的 crawl_results 取回原文核实，仍无法确认则丢弃。
4. B2 按 include/exclude 过滤并聚类为事件组，逐组执行 high 信源校验（≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2），写入 event_list.json；可拒绝单源爆料；域名数卡线或来源事实冲突时用 research-orchestrator 交叉验证，冲突无法消解则丢弃。
5. B3 撰写日报 daily/YYYY-MM-DD.md 与 summary.json。
6. 产物统一写入：early_bird/热点资讯追踪/早鸟雷达-金融/
7. 若 empty_silent=true 且 B2/B3 确认为空结果，仍需完成 B3/B4 空结果日报，然后按指引静默结束（no_reply）。
8. 完成后只重复脚本要求的信息，不要直接发完整日报给用户。
```

## 4. 早鸟雷达-消费（每天 08:42）

```text
早鸟雷达-消费 · 每日 briefing
1. 执行 early_bird_briefing(action="init", setup_token="setup_63c56ee9")，读取消费领域完整追踪契约与首步指引。
2. 按脚本指引完成完整 briefing 流程（B1→B2→B3→B4），直到状态为 DONE；中途校验未通过时，按返回的错误项修正产物后重新提交同一步骤。
3. B1 用 web_search 围绕契约 search_seeds 检索 24-48 小时候选，再用 find-news 补充多引擎与垂类源（微信公众号/GitHub/Reddit），必要时用 multi-source-research 扩面去重，写入 raw_candidates.json；发布时间不确定的候选用 find-news 的 crawl_results 取回原文核实，仍无法确认则丢弃。
4. B2 按 include/exclude 过滤并聚类为事件组，逐组执行 high 信源校验（≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2），写入 event_list.json；来源或时间不确定的事件不提交；域名数卡线或来源事实冲突时用 research-orchestrator 交叉验证，冲突无法消解则丢弃。
5. B3 撰写日报 daily/YYYY-MM-DD.md 与 summary.json。
6. 产物统一写入：early_bird/热点资讯追踪/早鸟雷达-消费/
7. 若 empty_silent=true 且 B2/B3 确认为空结果，仍需完成 B3/B4 空结果日报，然后按指引静默结束（no_reply）。
8. 完成后只重复脚本要求的信息，不要直接发完整日报给用户。
```

## 5. 早鸟雷达-商业（每天 08:55）

```text
早鸟雷达-商业 · 每日 briefing
1. 执行 early_bird_briefing(action="init", setup_token="setup_d93a5b44")，读取商业领域完整追踪契约与首步指引。
2. 按脚本指引完成完整 briefing 流程（B1→B2→B3→B4），直到状态为 DONE；中途校验未通过时，按返回的错误项修正产物后重新提交同一步骤。
3. B1 用 web_search 围绕契约 search_seeds 检索 24-48 小时候选，再用 find-news 补充多引擎与垂类源（微信公众号/GitHub/Reddit），必要时用 multi-source-research 扩面去重，写入 raw_candidates.json；发布时间不确定的候选用 find-news 的 crawl_results 取回原文核实，仍无法确认则丢弃。
4. B2 按 include/exclude 过滤并聚类为事件组，逐组执行 high 信源校验（≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2），写入 event_list.json；来源或时间不确定的事件不提交；域名数卡线或来源事实冲突时用 research-orchestrator 交叉验证，冲突无法消解则丢弃。
5. B3 撰写日报 daily/YYYY-MM-DD.md 与 summary.json。
6. 产物统一写入：early_bird/热点资讯追踪/早鸟雷达-商业/
7. 若 empty_silent=true 且 B2/B3 确认为空结果，仍需完成 B3/B4 空结果日报，然后按指引静默结束（no_reply）。
8. 完成后只重复脚本要求的信息，不要直接发完整日报给用户。
```

## 6. 早鸟雷达-人才（每天 09:08）

```text
早鸟雷达-人才 · 每日 briefing
1. 执行 early_bird_briefing(action="init", setup_token="setup_26010b88")，读取人才领域完整追踪契约与首步指引。
2. 按脚本指引完成完整 briefing 流程（B1→B2→B3→B4），直到状态为 DONE；中途校验未通过时，按返回的错误项修正产物后重新提交同一步骤。
3. B1 用 web_search 围绕契约 search_seeds 检索 24-48 小时候选，再用 find-news 补充多引擎与垂类源（微信公众号/GitHub/Reddit），必要时用 multi-source-research 扩面去重，写入 raw_candidates.json；发布时间不确定的候选用 find-news 的 crawl_results 取回原文核实，仍无法确认则丢弃。
4. B2 按 include/exclude 过滤并聚类为事件组，逐组执行 high 信源校验（≥3 独立域名，Tier-1 官方源 ×1 或 Tier-2 主流媒体 ×2），写入 event_list.json；来源或时间不确定的事件不提交；域名数卡线或来源事实冲突时用 research-orchestrator 交叉验证，冲突无法消解则丢弃。
5. B3 撰写日报 daily/YYYY-MM-DD.md 与 summary.json。
6. 产物统一写入：early_bird/热点资讯追踪/早鸟雷达-人才/
7. 若 empty_silent=true 且 B2/B3 确认为空结果，仍需完成 B3/B4 空结果日报，然后按指引静默结束（no_reply）。
8. 完成后只重复脚本要求的信息，不要直接发完整日报给用户。
```

## 7. 早鸟工作台聚合（每天 09:45）

```text
早鸟工作台聚合（每日刷新工作台）
1. 执行 early_bird_aggregate(action="snapshot")。
2. 聚合器读取六个领域最新日报（daily/YYYY-MM-DD.md + event_list.json + summary.json），渲染 early_bird/工作台/index.html。
3. 同时保存快照到 early_bird/工作台/daily/YYYY-MM-DD.html，并写出 manifest.json。
4. 失败时保留上一次结果（原子写入，不会清空旧 index.html），并把错误写回 early_bird/aggregate.log。
5. 向我简报：数据日期、已出报领域数、事件总数、Tier-1/Tier-2 引用数、独立域名合计、待处理告警数；存在缺报或告警时逐项列出领域与原因。
```

---

## 时刻表速查

| 链条 | 时间 | setup_token | 执行内容 |
| --- | --- | --- | --- |
| 科技 | 08:03 | `setup_0da2e5ce` | briefing B1→B4 |
| 医学 | 08:16 | `setup_244e21da` | briefing B1→B4 |
| 金融 | 08:29 | `setup_ccbd5295` | briefing B1→B4 |
| 消费 | 08:42 | `setup_63c56ee9` | briefing B1→B4 |
| 商业 | 08:55 | `setup_d93a5b44` | briefing B1→B4 |
| 人才 | 09:08 | `setup_26010b88` | briefing B1→B4 |
| 聚合 | 09:45 | — | snapshot → index.html + daily/ → 邮件推送 |

## 自动化说明（重要）

本项目**已内置常驻调度器**，上表时刻由 `src/early_bird_scheduler.py` 自动触发，
**无需在外部平台配置日程**。上面 7 条提示词保留用于两种场景：

1. 你仍想用外部日程平台触发（把提示词贴到平台日程里，平台调用本智能体即可）；
2. 手动补跑某个领域时，把对应提示词直接发给智能体。

聚合链完成后会自动发送当日邮件摘要（QQ 邮箱 SMTP，凭据在 `config/credentials.env`）。
发送失败自动入队重试；无论是否发出，摘要都写入站内收件箱 `early_bird/工作台/inbox/`。

手动触发也可走 HTTP 接口，无需粘贴提示词：

```bash
curl -X POST http://127.0.0.1:8010/api/user/agent/early-bird/run \
  -H 'Content-Type: application/json' \
  -d '{"chain":"tech","date":"2026-11-25","push":false}'

curl -X POST http://127.0.0.1:8010/api/user/agent/early-bird/push \
  -H 'Content-Type: application/json' -d '{"date":"2026-11-25"}'
```

## 路径映射（原 Coze → 本项目）

| 原路径 | 本项目路径 |
| --- | --- |
| `/Coze/Drive/编程专家/热点资讯追踪/` | `early_bird/热点资讯追踪/` |
| `/Coze/Drive/编程专家/早鸟工作台/工作台/index.html` | `early_bird/工作台/index.html` |
| `/Coze/Drive/编程专家/早鸟工作台/工作台/daily/` | `early_bird/工作台/daily/` |
| `/Coze/Drive/编程专家/早鸟工作台/aggregate.log` | `early_bird/aggregate.log` |
| `topic_tracking` 技能 + `guide.py` | `early_bird_briefing` 工具 / `early_bird/guide.py` |
| `aggregate.py snapshot` | `early_bird_aggregate(action="snapshot")` / `early_bird/aggregate.py snapshot` |

六领域 `setup_token` 与原设定完全一致，无需改动。

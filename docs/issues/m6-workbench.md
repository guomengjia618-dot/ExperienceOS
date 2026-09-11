# M6 工作台（v0.7.0 目标）

把 AI 层从"命令行工具"升级为"可检验、可展示的系统"：检查点化的证据简报
工作流、带断言的评测集，以及一个零依赖的本地浏览器工作台。

约定沿用：每个 Issue 独立可交付、可验收；`status=draft` 之外的写入永远
需要人工确认；AI 只提议，人类决定。

| Issue | 标题 | 优先级 | 状态 |
| --- | --- | --- | --- |
| #032 | Title: Evidence-brief workflow + evaluation harness | P0 | ✅ |
| #033 | Title: Local browser workbench (`experienceos web`) | P0 | ✅ |
| #034 | Title: Workbench run-history dropdown redesign | P1 | ✅ |

> 编号说明：#023–#026 曾预留给一次未落地的 M5 后重构方案，编号作废保留，
> 此后从 #032 续起。

---

## #032

Title: Evidence-brief workflow with read-only tools and an evaluation harness

区域：`area/ai`　难度：advanced　优先级：P0

模型不能凭空作答：工作流强制模型先通过三个只读工具（检索、读取、证据
统计）检查本地档案，再输出结构化简报；引用必须逐一对应本次运行中实际
读取到的证据位置，否则判为不接地（grounding failure）并暂停。

Acceptance Criteria:

- [x] `EvidenceBriefWorkflow.start/resume` 以原子 JSON 检查点持久化每轮
      状态（`<home>/workflows/wf_*.json`），中断后可从保存进度继续。
- [x] 工具注册表只暴露读路径：`search_experiences` / `get_experience` /
      `get_evidence_stats`；参数经 pydantic 严格校验。
- [x] 引用接地校验：`citations[].evidence_locations` 必须是本次
      `get_experience` 读到的记录中存在的位置。
- [x] `experienceos ai eval` 确定性回归 9/9 通过（工具序列、schema、
      接地、期望内容、错误恢复五类断言）；`--live` 可用真实模型跑同一
      数据集；报告默认脱敏（错误分类化，不含用户内容）。
- [x] 请求指标（延迟/重试/token/可选成本）持久化为脱敏运行报告。
- [x] 供应商中立：`openai-compat` 与 `openai-responses` 开箱即用，
      workflow 只依赖 provider 协议。

## #033

Title: Local browser workbench (`experienceos web`)

区域：`area/ai`　难度：intermediate　优先级：P0

零额外依赖（Python 标准库 `http.server` + pydantic）的本地工作台：
浏览经历、离线演示模式（合成数据 + 确定性回放模型，完整走一遍工具循环）、
真实模式（配置模型 + 密钥）、运行历史与断点恢复。只绑定 127.0.0.1。

Acceptance Criteria:

- [x] 演示模式完全离线可用；演示数据显式标注 `ai:synthetic-demo`。
- [x] API 仅接受工作台自身来源（Host/Origin/Sec-Fetch-Site 校验 +
      `X-ExperienceOS` 请求头），响应带严格 CSP。
- [x] 不记录访问日志；原始异常不出网（统一脱敏文案）。
- [x] 运行记录与检查点落在 `<home>/workbench/`，重启后可恢复展示。

## #034

Title: Workbench run-history dropdown redesign

区域：`area/ai`　难度：good first issue　优先级：P1

原生 `<select>` 无法承载运行记录的区分信息（只有"模式 · 状态 · 日期"，
同日多次运行不可分辨）。重做为自定义 listbox：问题摘要为主文案，状态
圆点（运行中呼吸/暂停琥珀/完成绿），相对时间，键盘可导航，Esc/外点
关闭，当前项高亮。

Acceptance Criteria:

- [x] 每条记录可辨识：问题文本 + 状态圆点 + 模式 + 相对时间。
- [x] 键盘操作完整（ArrowDown 打开、上下移动、Enter 选择、Esc 关闭）。
- [x] 选择记录恢复该次运行的模式、问题与结果视图。

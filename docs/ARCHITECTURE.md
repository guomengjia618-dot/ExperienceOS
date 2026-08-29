# ExperienceOS 架构设计

> 本文档描述 ExperienceOS 的分层架构、数据流与关键设计决策（ADR 风格）。
> 任何改变下述决策的 PR 应先更新本文档。

## 1. 总览

ExperienceOS 是一个**本地优先**的个人经历知识库。核心抽象是
Experience（经历资产）：统一建模工作项目、实习、开源贡献、竞赛、毕业设计、
课程实践、个人作品与研究项目。

```
┌────────────────────────────────────────────────────────────┐
│                        用户接口层                           │
│   CLI (typer)          API (FastAPI, M4)      Web UI (M4+) │
├────────────────────────────────────────────────────────────┤
│                        服务层（用例）                       │
│   ingest（导入）  enrich（提炼）  interview（录入）          │
│   search / export / stats                                   │
├──────────────┬─────────────────────┬───────────────────────┤
│  connectors  │        ai           │      exporters        │
│  github      │  LLMProvider 协议    │  markdown / json-resume│
│  git-repo    │  OpenAI 兼容实现     │  (M3)                 │
│  resume      │  版本化 Prompts      │                       │
├──────────────┴─────────────────────┴───────────────────────┤
│                      storage 存储层                         │
│   ExperienceStore（文件 source of truth）+ 内存查询引擎      │
├────────────────────────────────────────────────────────────┤
│                      core 领域层                            │
│   Experience / Evidence / Source 模型 · ULID · 错误体系     │
└────────────────────────────────────────────────────────────┘
```

依赖方向自上而下单向依赖 `core`。`core` 不依赖任何其他层。

## 2. 数据流

```
碎片来源                    统一抽象                    输出
─────────                ──────────                ─────────
代码 / 本地仓库   ─┐                        ┌─→ Markdown 档案
GitHub 贡献       ├─→ Connector ─→ 草稿      ├─→ JSON Resume
简历 / 文档       │   (status=draft)          ├─→ 技能时间线
对话描述          ─┘        │                 └─→ API / 查询
                             ▼
                    AI 提案（interview/enrich）
                             │  用户逐项确认 ←── 关键闸门
                             ▼
                Experience Asset（status=active，
                  evidence 挂证据，source 记录来源）
                             │
                             ▼
                    ~/.experienceos/experiences/*.json
```

两条铁律贯穿所有数据流：

1. **AI propose, human decide**：AI 的任何产出先以提案呈现，用户确认后才
   入库；`source.created_by` 如实标记 `user` 或 `ai:<model>`。
2. **能力关联证据**：contribution / result 鼓励挂 Evidence（repo、commit、
   PR、文档）。`stats` 的 evidence coverage 是知识库的健康指标。

## 3. 数据模型

见 `src/experienceos/core/models.py` 与 README 中的示例 JSON。要点：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 模型版本锚点，未来迁移的依据（当前 1） |
| `id` | `exp_` + 26 位 ULID，时间可排序，天然按新旧排序 |
| `type` | 9 种经历类型枚举（见 ExperienceType） |
| `period` | `YYYY-MM` 精度；`end=null` 表示进行中 |
| `contribution/challenge/solution/result` | STAR 结构化叙事，list[str] |
| `evidence[]` | 证据引用（kind + location），存引用不存内容 |
| `tags` / `technology` | 归一化标签（清洗去重，大小写不敏感比较） |
| `status` | draft / active / archived —— 记录的生命周期 |
| `source` | 溯源：origin（manual/github/resume/interview/…）+ created_by |

模型统一 `extra="forbid"`：经历文件是**人可手改的 JSON**，拼写错误的键必须
立即报错，而不是被静默丢弃。`validate_assignment=True` 让 CLI 的 `set` /
`add-item` 在赋值时走完整校验。

## 4. 关键设计决策（ADR）

### D1：文件是 source of truth，不引入数据库

**决策**：每条经历一个 JSON 文件（`<home>/experiences/<id>.json`），原子写
（临时文件 + `os.replace`），读取时逐文件加载；查询在内存完成。

**理由**：个人知识库的量级是数百条而非百万条；文件人可读、可 diff、可被
git 版本化、可随身拷贝。任何「索引」都应是可重建的派生物。

**代价与边界**：记录超过 ~1k 条时全量加载会变慢——届时引入 SQLite FTS5
索引（M4），文件仍是 truth，索引可随时 `index rebuild`。

### D2：为什么是 Experience 而不是 Project

用户参与过的远不止代码项目（毕业设计、竞赛、实习……）。`type` 枚举覆盖
九类经历，所有下游能力（导入、提炼、导出）只面对一种抽象，避免为每类
经历维护平行模型。

### D3：损坏容忍（corruption tolerance）

一个坏文件不能让整个知识库不可用：`list_all()` 跳过并 warn，`validate`
命令逐文件报告问题。这与「个人数据是资产」的定位一致——可用性优先，
问题显式暴露。

### D4：AI 层只依赖协议，不锁定厂商

`LLMProvider` 的核心接口是 `generate(messages, response_schema, tools)`，
同时保留 `complete(messages) -> str` 作为纯文本兼容入口。目前有两个 Adapter：
OpenAI-compatible Chat Completions 请求 `/chat/completions`；Responses Adapter
请求 `/responses`，并把 `response.output` 中的 function-call item 与本地
`function_call_output` 按 `call_id` 回放。工作流不依赖具体 Adapter。

Responses 请求使用 `store=false`。为兼容需要跨轮保留推理状态的模型，请求显式
包含 `reasoning.encrypted_content`，检查点只回放 API 返回的加密状态与响应项，
不保存明文隐藏推理。

两个 Adapter 共用 HTTP transport：按类别记录 timeout / network / rate_limit /
server_error / http_error，支持有限次数的指数退避、jitter、`Retry-After` 和总重试
时间预算。成功或失败都会产生不含 prompt 的 request metrics；request ID、延迟、
tokens、重试数和按配置价格估算的成本可写入脱敏报告。价格不是硬编码的事实，
未配置价格时成本为 `null`。

Evidence Brief Agent 暴露 3 个只读本地工具：检索经历、按 ID 读取完整记录、
统计证据覆盖率。模型只能提出调用，参数由服务端验证后才执行；最终 citation
必须引用本轮实际读取的记录，evidence location 也必须存在于原始记录。

Workflow 状态保存在 `<home>/workflows/<wf_id>.json`，每个模型轮次和工具
结果后都会原子更新。进程终止、网络失败或 Schema 校验失败时，用户可按
workflow ID 续跑；完成的 Tool `call_id` 会被去重，避免 interrupted execution
后重复执行。API Key 不进入消息或检查点。`<home>/reports/` 中的分享报告只含
运行指标，不含用户问题、模型回答或 Tool 返回内容。

评测数据位于 `evals/experience_brief.jsonl`，每个 AI 辅助起草的合成 case
都包含 Tool 顺序、状态、文本和恢复预期。数据来源、复核状态和 SHA-256 记录在
`evals/manifest.json`。录制模式用于确定性回归，明确不解释为模型准确率；
`--live` 只是在同一组合成预期上产生一次小规模模型表现和运行指标，仍不代表
真实用户任务分布。

### D5：CLI-first

核心逻辑（storage/query）与接口解耦，CLI 先行是因为它便宜、可脚本化、
易测试（CliRunner 驱动端到端用例）。API / Web UI 在同一套服务层上构建。

### D6：ID 前缀解析

CLI 接受任意唯一前缀（`exp_01H` 或 `01H`），`ExperienceStore.resolve`
负责展开；歧义前缀报 `AmbiguousIdError`。这是终端工具长期可用性的关键。

## 5. 目录结构

```
src/experienceos/
  core/         # 领域层：models.py / ulid.py / errors.py
  storage/      # store.py（文件仓库）/ query.py（查询引擎）
  connectors/   # base.py（Extractor 协议+草稿）/ registry.py（路由注册表）
  ai/           # Provider Adapters / HTTP transport / Tools / Workflow / Evals
  cli/          # app.py（命令）/ render.py（rich 渲染）
  config.py     # home 解析 + config.toml 读写
tests/          # 单元 + CLI 端到端 + GitHub fixtures + 失败与恢复回归
evals/          # AI 辅助合成回归集 + 数据来源 manifest
docs/           # 架构 / 路线图 / Issue 拆分
```

## 6. 配置与安全

- Home 解析优先级：`--home` > `$EXPERIENCEOS_HOME` > `~/.experienceos`。
- API key / `GITHUB_TOKEN` 永不落盘：config.toml 只存 `api_key_env`（环境变量名），
  GitHub token 仅从环境变量读取。
- `.gitignore` 排除 `.experienceos/`，防止个人知识库被误提交。
- 429 / 5xx 才按策略重试；其他 4xx 直接失败，防止无意义重放。
- `request_id` 会进入错误日志和脱敏报告，便于排障；日志不包含 Key 或 prompt。

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
│  CLI (typer)    API (FastAPI, 只读)    Web 工作台 (#033)    │
├────────────────────────────────────────────────────────────┤
│                        服务层（用例）                       │
│   ingest（导入）  enrich（提炼）  interview（录入）          │
│   search / export / stats / verify（证据核验，M6）           │
├──────────────┬─────────────────────┬───────────────────────┤
│  connectors  │        ai           │      exporters        │
│  github      │  证据简报工作流(#032) │  markdown / json-resume│
│  git-repo    │  只读工具 + 评测集    │  html                  │
│  project-files  provider(兼容/Responses)                    │
│  resume      │  版本化 Prompts      │                       │
├──────────────┴─────────────────────┴───────────────────────┤
│                      storage 存储层                         │
│   ExperienceStore（文件 source of truth）+ 内存查询引擎      │
├────────────────────────────────────────────────────────────┤
│                      core 领域层                            │
│   Experience / ExperienceDraft / Evidence / Source 模型     │
│   ULID · 错误体系 · 证据护栏                                 │
└────────────────────────────────────────────────────────────┘
```

依赖方向自上而下单向依赖 `core`；兄弟层之间互不依赖（connectors 与
ai 之间需要协作时，协议定义在被依赖方、实现由服务层注入，见 D7）。
`core` 不依赖任何其他层。唯一豁免：ai 的只读工具缝隙（tools / 评测 /
demo）允许向下 import storage——工具必须读真实档案才能约束模型，这是
向下的、无环的依赖，由 `tests/test_layering.py` 的规则表显式放行。

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

`LLMProvider` 是 `generate(messages, response_schema, tools) -> ModelResponse`
的 Protocol——结构化输出与函数工具调用是一等公民；`complete()` 只是兼容
助手。随箱带两个实现（OpenAI 兼容 chat 与 Responses API），由
`ai.factory.create_provider` 按配置选择；工作流对厂商零感知。Prompt 是
带版本的代码，测试断言其不变量（不捏造、要求 JSON、标记 provenance）。
模型请求的指标（延迟 / token / 重试 / 可选成本费率）由传输层采集并进入
脱敏报告；重试预算、抖动与费率全部显式配置，不靠魔法数。

### D5：CLI-first

核心逻辑（storage/query）与接口解耦，CLI 先行是因为它便宜、可脚本化、
易测试（CliRunner 驱动端到端用例）。API / Web UI 在同一套服务层上构建。

### D6：ID 前缀解析

CLI 接受任意唯一前缀（`exp_01H` 或 `01H`），`ExperienceStore.resolve`
负责展开；歧义前缀报 `AmbiguousIdError`。这是终端工具长期可用性的关键。

### D7：兄弟层协作靠协议注入，不靠横向 import（M5 #028）

**决策**：connectors 与 ai 是兄弟层，互不 import。需要 AI 阅读的
connector（如 PDF 简历）通过 `connectors.base` 定义的
`MaterialDraftExtractor` / `AcceptsMaterialExtractor` 协议接受注入；
`ai.extraction.AIExtraction` 结构化实现该协议，由组合根
（`services.ingest`）按能力接线——没有针对具体 connector 的特判。

**理由**：M5 审查发现 ai ↔ connectors 曾存在双向横向依赖
（ExperienceDraft 在 connectors、PDF 管线反向 import ai），任何一环
改动都会波及兄弟层。修正后：`ExperienceDraft` 下沉 core（提案是领域
概念）；提取管线归位 ai；依赖箭头统一指下。第三方 connector 想要 AI
能力时实现同一协议即可，无需理解 ai 层。

**代价与边界**：多一层间接（协议 + 组合根接线）。分层守卫测试
（`tests/test_layering.py`，AST 静态检查）保证方向不被再次破坏。

### D8：查询语义只有一个定义处（M5 #029）

**决策**：`services.query_results` 是所有接口（CLI / API）的统一查询
入口。FTS 索引只做**候选预过滤**——命中集合交给内存引擎做最终过滤与
打分；得分、命中字段、排序在「有索引」与「无索引」两条路径上逐位一致
（守卫测试断言）。

**理由**：审查发现 CLI 与 API 曾走两条语义不同的路径，且 FTS 路径会
丢弃相关性排序。查询语义必须只有一个定义处（`storage.query.search`），
索引是加速器而不是第二种真相。

### D9：证据简报工作流——先读档、接地、可恢复（M6 #032）

**决策**：`EvidenceBriefWorkflow` 把「模型回答关于本地档案的问题」变成
一个有界的状态机：(1) 模型只能通过三个只读工具
（`search_experiences` / `get_experience` / `get_evidence_stats`）接触
档案；(2) 输出是严格 schema 的 `EvidenceBrief`，其中每条引用的
`evidence_locations` 必须逐一对应**本次运行中** `get_experience` 读到的
证据位置——不接地即 `WorkflowError`，运行转 paused 而不是输出幻觉；
(3) 每轮对话原子持久化到 `<home>/workflows/wf_*.json`，中断后
`resume` 精确续跑，已完成的工具调用不会重放；(4) 9 用例评测集把工具
调用序列、schema 合法性、接地与恢复断言成回归测试。

**理由**：LLM 的失败模式是「自信地编造」。与其在输出后过滤，不如在
工作流层让编造**无法通过**：引用必须指向本次读取的真实证据。检查点
则把「网络断了」从错误降级为暂停。

**代价与边界**：接地校验是**存在性校验**（引用的证据确实被读取过），
不是语义蕴含校验——它不能保证结论被证据支持，只能保证结论的出处可
回溯。`--recorded`/评测回放让这条路径完全离线可测；供应商差异被 D4
的协议隔离。

### D10：证据核验是镜子，不是改写器（M6）

**决策**：`services.verify` + `experienceos verify` 把记录声明的证据
拿到网络对证——GitHub 仓库 / commit（含作者与日期）/ PR（作者、状态、
是否合并）逐条核验存在性；非 GitHub URL 只做存在性探测（不跟随重定
向，防探测被弹向内网）；本地路径如实跳过。结果只进报告（终端或
`--json`），**绝不回写记录**；发现失效证据以退出码 1 退出，供 CI 门禁。

**理由**：证据的价值在于可被证伪。核验如果顺手改写记录（比如自动加
"verified" 标记），就违背了「导出物是忠实投影」与「AI propose, human
decide」两条铁律——状态变化必须由人确认。

## 5. 目录结构

```
src/experienceos/
  core/         # 领域层：models.py / draft.py / ulid.py / errors.py / guardrails.py
  storage/      # store.py（文件仓库 + stat 缓存）/ query.py / fts.py / migrations.py
  connectors/   # base.py（协议+草稿+注入协议）/ languages.py / github / gitrepo
                #   / projectfiles / resume / registry.py
  ai/           # workflow.py（证据简报状态机）/ tools.py（只读工具）
                #   / evaluation.py（评测 harness）/ demo.py（录播 provider）
                #   / provider.py + transport.py + responses.py（协议与实现）
                #   / extraction.py / interview.py / prompts.py（版本化模板）
  services/     # experiences.py / ingest.py / homeops.py / verify.py（证据核验）
  exporters/    # base.py / markdown / json_resume / html / registry.py
  web/          # server.py + demo.py + static/（本地工作台，零依赖）
  cli/          # app.py（命令）/ render.py（rich 渲染）
  api/          # app.py（FastAPI 薄壳）
  config.py     # home 解析 + config.toml 读写
tests/          # 单元 + CLI 端到端（含离线 GitHub API fixtures）+ 分层守卫
evals/          # 9 条带标签评测用例 + sha256 manifest
examples/       # 可运行的离线 agent 演示
docs/           # 架构 / 路线图 / Issue 拆分
```

## 6. 配置与安全

- Home 解析优先级：`--home` > `$EXPERIENCEOS_HOME` > `~/.experienceos`。
- API key / `GITHUB_TOKEN` 永不落盘：config.toml 只存 `api_key_env`（环境变量名），
  GitHub token 仅从环境变量读取。
- `.gitignore` 排除 `.experienceos/`，防止个人知识库被误提交。

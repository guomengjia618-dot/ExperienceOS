# ExperienceOS 路线图

版本节奏：每个 Milestone 对应一个 minor 版本，完成即打 tag 发 Release。
Issue 明细见 [issues/](issues/)，标签体系：`area/core` `area/cli`
`area/ai` `area/connector` `area/exporter` `area/docs` `good first issue`。

## M0 — 基础（v0.1.0）✅ 2026-08-25

**目标**：最小可用的本地经历知识库。

- ✅ Experience 数据模型（pydantic v2，严格校验 + schema 版本锚点）
- ✅ ULID 时间可排序 ID + 前缀解析
- ✅ 文件存储层（原子写、损坏容忍、validate 报告）
- ✅ 内存查询引擎（加权全文 + 类型/标签/技术/时间窗过滤）
- ✅ CLI：init / add / list / show / search / set / add-item / edit /
  delete / stats / validate / path
- ✅ AI 层接口预埋（Provider 协议 + 版本化 Prompt）
- ✅ 测试 95 例全绿 + ruff + CI（Ubuntu & Windows × Python 3.10-3.13）

## M1 — 导入（v0.2.0）✅ 2026-08-29

**目标**：让「已有碎片」自动变成经历草稿，冷启动不再痛苦。

- ✅ #006 Connector 框架（Extractor 协议 + 注册表 + `import` 命令）
- ✅ #007 GitHub 导入器（仓库 / commit / PR / issue → 草稿 + 证据）
- ✅ #008 本地 git 仓库分析器（log / 语言统计 → 草稿 + 证据）
- ✅ #009 简历导入器（Markdown / 纯文本解析，PDF 依赖 M2 的 AI 提取）

## M2 — 智能（v0.3.0）✅ 2026-08-29

**目标**：AI 成为「不撒谎的采访者与整理员」。

- ✅ #010 LLM Provider 接线（配置校验、offline mock provider、超时与重试）
- ✅ #011 `interview` 命令（STAR 引导对话 → 草稿，全程引用证据）
- ✅ #012 `enrich` 命令（对已有记录提出 contribution/result/reflection
  改进提案，逐项 diff 确认；越界提案直接丢弃）
- ✅ #013 证据护栏（`lint`：无证据的量化断言被标记而非静默接受）

## M3 — 输出（v0.4.0）✅ 2026-08-29

**目标**：知识库的价值外显——一键产出可信材料。

- ✅ #014 Exporter 框架（协议 + 注册表）
- ✅ #015 Markdown 个人档案 / 时间线导出
- ✅ #016 JSON Resume 兼容导出
- ✅ #017 技能画像与统计（技术频率时间线、共现 Top-N）

## M4 — 平台（v0.5.0）✅ 2026-08-29

**目标**：从个人工具长成生态。

- ✅ #018 FastAPI 服务（OpenAPI 文档，复用服务层）
- ✅ #019 插件系统（entry-points 注册 connector / exporter）
- ✅ #020 schema 迁移框架（schema_version 升级管线）
- ✅ #021 备份与同步（home 目录 git 化：`experienceos sync`）
- ✅ #022 SQLite FTS5 索引（记录 >1k 时的性能路径，索引可重建）

## M5 — 架构加固（v0.6.0）✅ 2026-08-30

**目标**：全库架构审查后的结构性修复——补齐输入矩阵、消除层间循环、
统一查询语义，不做任何补丁式修复。

- ✅ #027 项目文件夹导入器（无版本控制的目录 → 草稿；共享语言映射模块）
- ✅ #028 分层循环消除（ExperienceDraft 下沉 core；AI 提取管线独立成
  模块；PDF 路线改协议注入，connectors 与 ai 互不依赖）
- ✅ #029 查询语义统一（`services.query_results` 保留排序元数据；FTS
  仅作候选预过滤，打分永远来自内存引擎；CLI 与 API 同路径）
- ✅ #030 确认闸门补全（interview 的逐字段确认现在包含 AI 采集的
  evidence，与其他字段同一人工闸门）
- ✅ #031 未来用户规划落档（设计师 / 研究人员 / 创作者的扩展路径，
  见下文「未来用户」）

## 未来用户

当前阶段聚焦开发者；数据模型与导出格式刻意保持职业中立（Experience
抽象不绑定代码项目），为以下人群预留扩展空间，预计在输入 connector
与模板层扩展，不动核心 schema：

- **设计师**（作品集 / 设计交付物的 connector 与 portfolio 导出模板）
- **研究人员**（论文 / 课题 / 实验记录的 connector 与学术履历导出）
- **创作者**（内容系列 / 作品集时间线的 connector 与展示模板）

## Backlog（暂不排期）

- #023 CLI i18n（中英双语 help）
- #024 mypy strict + 类型覆盖率门禁
- #025 文档站点（mkdocs-material）
- #026 Web UI（只读浏览 + 编辑确认，服务端复用 FastAPI）
- #032 CLI 命令分组拆分（命令数继续增长时按域拆为子模块）

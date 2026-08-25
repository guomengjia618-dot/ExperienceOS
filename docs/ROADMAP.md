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

## M1 — 导入（v0.2.0）🚧 下一个版本

**目标**：让「已有碎片」自动变成经历草稿，冷启动不再痛苦。

- ✅ #006 Connector 框架（Extractor 协议 + 注册表 + `import` 命令）
- #007 GitHub 导入器（仓库 / commit / PR / issue → 草稿 + 证据）
- #008 本地 git 仓库分析器（log / 语言统计 → 草稿 + 证据）
- #009 简历导入器（Markdown / 纯文本解析，PDF 依赖 M2 的 AI 提取）

## M2 — 智能（v0.3.0）

**目标**：AI 成为「不撒谎的采访者与整理员」。

- #010 LLM Provider 接线（配置校验、offline mock provider、超时与重试）
- #011 `interview` 命令（STAR 引导对话 → 草稿，全程引用证据）
- #012 `enrich` 命令（对已有记录提出 contribution/result/reflection
  改进提案，逐项 diff 确认）
- #013 证据护栏（`lint`：无证据的量化断言被标记而非静默接受）

## M3 — 输出（v0.4.0）

**目标**：知识库的价值外显——一键产出可信材料。

- #014 Exporter 框架（协议 + 注册表）
- #015 Markdown 个人档案 / 时间线导出
- #016 JSON Resume 兼容导出
- #017 技能画像与统计（技术频率时间线、经历-技术图谱）

## M4 — 平台（v0.5.0）

**目标**：从个人工具长成生态。

- #018 FastAPI 服务（OpenAPI 文档，复用服务层）
- #019 插件系统（entry-points 注册 connector / exporter）
- #020 schema 迁移框架（schema_version 升级管线）
- #021 备份与同步（home 目录 git 化：`experienceos sync`）
- #022 SQLite FTS5 索引（记录 >1k 时的性能路径，索引可重建）

## Backlog（暂不排期）

- #023 CLI i18n（中英双语 help）
- #024 mypy strict + 类型覆盖率门禁
- #025 文档站点（mkdocs-material）
- #026 Web UI（只读浏览 + 编辑确认，服务端复用 FastAPI）

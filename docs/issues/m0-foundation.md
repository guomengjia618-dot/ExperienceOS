# M0 — 基础（v0.1.0，已完成）

> 完成记录。全部随 2026-08-25 的 v0.1.0 发布关闭，验收标准见 git tag。

## #001 项目骨架与工程基线 ✅

- **Labels**: `area/infra` · P0
- pyproject（hatchling，src-layout）、LICENSE(MIT)、.gitignore、CHANGELOG、
  ruff（含 typer B008 白名单）、pytest 配置、GitHub Actions CI
  （Ubuntu/Windows × Python 3.10-3.13）。

## #002 Experience 数据模型 ✅

- **Labels**: `area/core` · P0
- pydantic v2 模型：Experience / Period / Evidence / Source + 9 类
  ExperienceType + Status；`extra="forbid"`、`validate_assignment=True`、
  `schema_version` 锚点；ULID 生成（stdlib、进程内单调）。

## #003 文件存储层 ✅

- **Labels**: `area/core` · P0
- 一条经历一个 JSON 文件；原子写（tmp + os.replace）；损坏容忍的
  `list_all`；`validate()` 报告；唯一前缀 `resolve()`。

## #004 内存查询引擎 ✅

- **Labels**: `area/core` · P0
- 加权全文（title > tags/technology > STAR 字段 > 正文），多词 AND 可跨
  字段命中；type/status/tag/technology/时间窗过滤；分数并列时新经历优先。

## #005 CLI MVP ✅

- **Labels**: `area/cli` · P0
- 12 个命令：init / add（向导）/ list / show / search / set / add-item /
  edit（$EDITOR + 校验闭环 + 断点续改）/ delete（确认）/ stats（证据
  覆盖率）/ validate / path。友好错误处理（`experienceos --help`）。

## #005b AI 层接口预埋 ✅

- **Labels**: `area/ai` · P1
- `LLMProvider` Protocol + OpenAI 兼容实现骨架（`[ai]` extra）+ 版本化
  Prompt（intake / extraction），契约测试锁定「不捏造 / 要 JSON / 标
  provenance」三条不变量。

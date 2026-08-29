# M4 — 平台（v0.5.0）

> 目标：从个人 CLI 工具长成可扩展的平台。前三个 Issue 是地基，顺序
> 建议依编号推进。

## #018 FastAPI 服务 ✅ 2026-08-29

**Labels**: `area/infra` · P0 · advanced

- [x] `experienceos-serve` 入口（`[api]` extra）：REST 暴露 list / show /
      search / stats（M4 只读 + 创建草稿，写操作仍走 CLI 确认闸门）
- [x] 服务层从 CLI 中剥离：`services/` 包承载用例，CLI 与 API 都是薄壳
      （这是本 Issue 的真实工作量所在）
- [x] OpenAPI 自动文档；CORS 默认关闭
- [x] 集成测试用 httpx ASGI transport，不起真实端口

## #019 插件系统 ✅ 2026-08-29

**Labels**: `area/infra` · P1 · advanced

- [x] entry-points 分组注册 connector / exporter：
      `[project.entry-points."experienceos.connectors"]`
- [x] 第三方包安装即注册；`experienceos plugins list` 展示来源与版本
- [x] 内置 connector / exporter 迁移到同一注册机制（吃自己的狗粮）
- [x] 插件加载失败不拖垮主程序（隔离 import，报告插件名）

## #020 schema 迁移框架 ✅ 2026-08-29

**Labels**: `area/core` · P0 · intermediate

- [x] `migrations/` 包：`schema_version N -> N+1` 的有序迁移函数注册表
- [x] 读路径遇到旧版本自动尝试迁移（备份原文件到 `<home>/backup/`）；
      `experienceos migrate --check` 只报告不执行
- [x] 以 v1 -> v2 的假想变更（例如给 Evidence 加必填字段）做演练测试

## #021 备份与同步 ✅ 2026-08-29

**Labels**: `area/infra` · P1 · `good first issue`

- [x] `experienceos sync`：home 目录若为 git 仓库则自动 commit（默认
      信息含变更记录数），非 git 仓库时提示一键 `git init`
- [x] `--push <remote>` 推送（私有仓库提醒写入文档）
- [x] `experienceos backup --out archive.zip` 全量打包（含 config）

## #022 SQLite FTS 索引 ✅ 2026-08-29

**Labels**: `area/core` `area/infra` · P2 · advanced

- [x] `experienceos index rebuild`：全量重建 FTS5 索引（中英混合分词
      用 unicode61 + 自定义 CJK 二元切分，评估后再定）
- [x] 查询引擎在索引存在且记录数超阈值时走 FTS，否则回退内存扫描；
      文件始终是 source of truth（索引可随时删除重建，行为有测试锁定）
- [x] benchmark 脚本（1k/5k/1w 条记录）验证阈值假设

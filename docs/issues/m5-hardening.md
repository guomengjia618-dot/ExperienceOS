# M5 — 架构加固（v0.6.0）

> 目标：全库架构审查后的结构性修复。五个 Issue 都是把「隐式约定」
> 变成「结构保证」，不允许补丁式修复——每一项都动结构而不是加判断。

## #027 项目文件夹导入器 ✅ 2026-08-30

**Labels**: `area/connector` · P0 · intermediate

- [x] `project-files` connector：无版本控制的项目目录 → 一份草稿
      （补齐输入矩阵中的「项目文件」，与 git-repo 按注册顺序自然分工）
- [x] 共享语言映射模块 `connectors/languages.py`，git-repo 复用同一份
      扩展名表（消除即将发生的复制）
- [x] 目录遍历安全：junk/build 目录剪枝、目录符号链接不跟随、文件数上限
- [x] 诚实规则：title 取目录名；description 是 README 原文摘录；无版本
      历史则 period 用显式 undated 占位并打 `undated` 标签；contribution
      保持为空（文件清单证明不了任何人的贡献）
- [x] `SourceOrigin.project_files` 枚举值；entry-points 注册（吃自己的狗粮）

## #028 分层循环消除 ✅ 2026-08-30

**Labels**: `area/core` `area/ai` `area/connector` · P0 · advanced

审查发现 ai ↔ connectors 存在双向横向依赖：
`ai/interview → connectors.base`（ExperienceDraft）与
`connectors/resume → ai.interview`（PDF 提取管线）。

- [x] `ExperienceDraft` 下沉到 `core/draft.py`（提案是领域概念，两个
      兄弟层都依赖它，只能放 core）；`connectors.base` 保留 re-export
- [x] 物料→草稿提取管线独立为 `ai/extraction.py`（提示词组装、容错
      JSON 解析、白名单映射、唯一的 JSON 重试）；`ai/interview.py` 只留
      会话特有逻辑
- [x] 依赖倒置：`MaterialDraftExtractor` / `AcceptsMaterialExtractor`
      协议定义在 `connectors.base`，`AIExtraction` 结构化实现之，由
      组合根（services.ingest）注入——connectors 从此不 import ai
- [x] 分层守卫测试：`tests/test_layering.py` 断言 ai 不依赖 connectors、
      core 不依赖任何上层

## #029 查询语义统一 ✅ 2026-08-30

**Labels**: `area/core` · P0 · intermediate

审查发现同一查询有两条语义不同的路径：API 走 `services.run_query`
（FTS 分发，但丢弃 FTS 排序与得分），CLI list/search 直接调内存
`search()`（无 FTS）——违背了 #018 建 service 层的初衷。

- [x] `services.query_results`：保留 `SearchResult`（得分/命中字段）的
      统一入口；CLI list/search 与 API 共用
- [x] 语义收敛：FTS 只做候选预过滤，最终过滤与打分永远来自内存引擎
      ——得分与排序在两条路径上逐位一致（守卫测试断言）
- [x] `run_query` / `list_experiences` / `search_experiences` 保持为
      扁平化别名，API 契约不变

## #030 确认闸门补全 ✅ 2026-08-30

**Labels**: `area/cli` `area/ai` · P0 · `good first issue`

「AI propose, human decide」要求每个字段过人工闸门，但 interview 的
逐字段确认漏掉了 `evidence`——AI 采集的证据候选被静默带入草稿。

- [x] evidence 进入确认循环（Enter=keep / d=drop all；细编辑提示用
      `experienceos edit`）
- [x] 证据渲染带 kind 与 location；守卫测试覆盖「drop 后草稿无证据」

## #031 未来用户规划落档 ✅ 2026-08-30

**Labels**: `area/docs` · P2 · `good first issue`

项目简报中的「未来可扩展：设计师 / 研究人员 / 创作者」此前未体现在
任何路线图文档中。

- [x] `docs/ROADMAP.md` 新增「未来用户」小节：三类人群、扩展位置
      （connector 与导出模板层）与「不动核心 schema」的边界
- [x] README 路线图表下方一句话指引，目标用户定义与简报对齐

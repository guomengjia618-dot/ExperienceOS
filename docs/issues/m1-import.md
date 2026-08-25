# M1 — 导入（v0.2.0）

> 用户故事总纲：作为开发者，我已经有 GitHub 仓库、本地代码和一份旧简历，
> 我希望 ExperienceOS 自动把它们变成**草稿**经历，而不是让我从零手填。

## #006 Connector 框架 ✅ 2026-08-25

**Labels**: `area/connector` `area/core` · P0 · intermediate

### 故事

作为用户，我希望所有导入来源走同一套机制，第三方可以注册新的来源。

### 验收标准

- [x] `experienceos.connectors.base.Extractor` 协议：
      `name: str`、`can_handle(source: str) -> bool`、
      `extract(source: str) -> Iterator[ExperienceDraft]`
- [x] `ExperienceDraft` 是带校验的草稿类型：底层是 `Experience.new()`
      产出（`status=draft`、`source.origin` 正确、evidence 尽量自动挂）
- [x] 注册表 `registry.py`：`register(extractor)` + `get(name)` +
      `find_handler(source)`，重复注册报错
- [x] CLI：`experienceos import <source>`（如 `github:owner/repo`、
      `path/to/repo`、`resume:cv.md`），草稿落盘后打印 id 列表与
      `show <id>` 提示
- [x] 草稿永远不会覆盖已有记录（id 冲突时报错）
- [x] 单元测试覆盖协议、注册表与 import 命令（fake extractor）

### 技术说明

`source` 用 `scheme:payload` 形式路由；无 scheme 视为本地路径。import
是**纯写入草稿**，不做 AI 提炼（那是 M2 的事），保证行为可预测。

## #007 GitHub 导入器

**Labels**: `area/connector` · P0 · advanced

### 故事

作为用户，我希望指定一个我参与过的仓库，ExperienceOS 拉取我在其中的
commit / PR / issue，生成一份有证据的草稿。

### 验收标准

- [ ] `experienceos import github:owner/repo [--author <user>]`，
      author 默认取 authenticated user
- [ ] 采集：仓库元信息（语言、描述、时间窗）、`?author=` 的 commit 列表、
      该作者的 PR 与 issue
- [ ] 产出：technology 取 repo languages；contribution 取 commit/PR 主题
      去重后的摘要行；evidence 自动挂 repo / commit / pull_request
- [ ] `GITHUB_TOKEN` 环境变量认证；无 token 时的公开仓库限流要有清晰
      错误信息
- [ ] 分页拉全（per_page=100 + Link header 跟随）；网络错误转为
      `ExperienceOSError` 子类
- [ ] 离线 fixture 测试（responses/recordings），CI 不打真实 API

### 技术说明

用 `httpx`（已在 `[ai]` extra，考虑挪到新的 `[github]` extra 或核心依赖，
在 PR 中决策并记录）。绝不捏造数字：commit 数、PR 数来自 API 计数。

## #008 本地 git 仓库分析器

**Labels**: `area/connector` · P1 · intermediate

### 故事

作为用户，我希望对本地某个 git 仓库跑一次分析，得到时间窗、语言构成与
我的提交行为摘要。

### 验收标准

- [ ] `experienceos import /path/to/repo [--author me@example.com]`
- [ ] 通过 `git log` 采集：时间窗（首/末提交）、我的 commit 数、变更规模
      中位数；不执行任何写操作 / 网络请求
- [ ] 语言构成按扩展名统计（内置映射表，不引入 linguist 依赖）
- [ ] evidence 挂 `repo`（本地路径）+ 若检测到 GitHub remote 挂 URL
- [ ] 非 git 目录给出可读错误；子模块/浅克隆不崩溃
- [ ] 用 tmp git 仓库 fixture 做集成测试（`git init` + 若干 commit）

## #009 简历导入器（文本）

**Labels**: `area/connector` · P1 · intermediate

### 故事

作为用户，我希望把已有的 Markdown / 纯文本简历解析成若干经历草稿。

### 验收标准

- [ ] `experienceos import resume:cv.md`：识别「项目/经历」小节与条目
      （支持常见中英文标题：项目经历 / 工作经历 / Projects / Experience）
- [ ] 每个条目 → 一份草稿：title、period（若可解析）、technology
      （行内技术名词启发式）、description（原句保留，不改写）
- [ ] 原文路径写入 `source.ref`；不使用 LLM（本 Issue 纯规则）
- [ ] 解析不出任何条目时给出明确失败信息
- [ ] fixture 覆盖中英文简历各一份
- [ ] PDF 支持明确推迟到 M2（#012 附带，依赖 AI 提取），在 `--help`
      中说明

### 技术说明

规则解析器放 `connectors/resume/`，小节识别用标题正则 + 缩进/空行分段，
足够覆盖 80% 常见简历结构；复杂排版交给 M2 的 AI 提取。

# M2 — 智能（v0.3.0）

> 用户故事总纲：作为用户，我希望 AI 像一位严谨的采访者和整理员——帮我
> 把记忆里的经历问出来、把草稿提炼成结构化资产，但**永远不替我编造事实**。

## #010 LLM Provider 接线

**Labels**: `area/ai` · P0 · intermediate

### 故事

作为用户，我希望在 config.toml 里配好模型（OpenAI / GLM / DeepSeek /
本地 Ollama），后续所有 AI 功能直接可用。

### 验收标准

- [ ] `OpenAICompatibleProvider` 完整实现（M0 骨架之上）：超时、一次
      重试（仅网络类错误）、429/5xx 转为 `AIProviderError` 并保留响应摘要
- [ ] `experienceos config set ai.model glm-4.7` 等 `config set/get/list`
      子命令（写入 config.toml）
- [ ] `experienceos ai check`：端到端连通性自检（发一条最小请求，报告
      模型名与耗时；无 key 时给出精确的环境变量提示）
- [ ] `MockProvider`（录制/回放固定回复）进入核心代码，供测试与
      `--dry-run` 使用
- [ ] API key 只从环境变量读取的行为有测试锁定

## #011 `interview` 命令（AI 采访录入）

**Labels**: `area/ai` `area/cli` · P0 · advanced

### 故事

作为用户，我不擅长写结构化描述，希望 AI 一次一个问题的把我的一段经历
问清楚，最后生成草稿让我确认。

### 验收标准

- [ ] `experienceos interview`：基于 `INTAKE_INTERVIEW_PROMPT_V1` 的多轮
      对话；每轮 AI 只问一个问题
- [ ] 对话中用户提到的 repo/URL/SHA 自动收集为候选 evidence
- [ ] 结束时用 `EXTRACTION_PROMPT_V1` 汇总为草稿（status=draft，
      `source.origin=interview`，`created_by="ai:<model>"`），渲染预览并
      逐字段确认（接受 / 编辑 / 丢弃），全部确认才落盘
- [ ] 提取失败（非法 JSON）自动重试一次，再失败则保存对话原文到
      `<home>/drafts/` 供下次续用
- [ ] `--no-ai` 模式退化为 #006 之前的纯向导（永远保留无 AI 路径）
- [ ] 用 MockProvider 的端到端测试覆盖完整流程

### 技术说明

对话历史不落盘、不上传（只发给所配置的 provider）；drafts/ 目录加入
`.gitignore` 建议。

## #012 `enrich` 命令（AI 提炼提案）

**Labels**: `area/ai` `area/cli` · P0 · advanced

### 故事

作为用户，我希望对我手填/导入的粗糙记录跑一次 enrich，AI 提出改进建议，
我逐条决定是否采纳。

### 验收标准

- [ ] `experienceos enrich <id>`：AI 读取记录，输出结构化**提案列表**：
      每条提案 = 字段路径 + 现值 + 建议值 + 一句理由
- [ ] 提案仅限：改写 contribution/challenge/solution/result 的表达、
      从 description 中抽取技术词到 technology；**禁止改动 title、period、
      evidence 与任何数值事实**（服务端二次校验，越界提案直接丢弃）
- [ ] 终端逐条 y/n 确认（默认 n），采纳的提案落盘并触发
      `updated_at`；`--all-yes` 显式跳过确认但打印 diff 摘要
- [ ] 附带：简历 PDF 提取（#009 的延伸）——pypdf 抽文本后走同一提取管线
- [ ] MockProvider 测试：含越界提案的响应被正确拒绝

## #013 证据护栏（`lint`）

**Labels**: `area/ai` `area/core` · P1 · intermediate

### 故事

作为准备面试的用户，我希望知道哪些记录的量化断言（"性能提升 3 倍"）
没有证据支撑，趁还记得时补上。

### 验收标准

- [ ] `experienceos lint [--all]`：扫描 contribution/result 中的量化
      模式（数字、倍数、百分比、排名），报告无 evidence 挂载的断言
- [ ] 每条报告：记录 id、命中句子、建议动作（补 evidence / 改写 / 标记
      source=interview 记忆来源）
- [ ] 规则实现为纯函数 `experienceos/core/guardrails.py`，独立可测；
      不依赖 LLM
- [ ] `lint` 结果退出码：有问题 1，无问题 0（可接入 CI 或 pre-commit）
- [ ] stats 输出增加 lint 汇总（无证据断言数）

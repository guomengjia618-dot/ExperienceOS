# 简历项目描述素材

> 用于简历「项目经历」栏与面试自我介绍。中文版按 STAR 展开；英文版对齐
> 硅谷风格动词开头。数字务必与仓库实际一致，不要夸大——这本身就是项目
> 理念。

---

## 中文版

**ExperienceOS — 开源 AI 个人经历操作系统**（个人项目 · Python · 2026）

- **项目**：独立设计并实现的本地优先（local-first）经历知识库，把 GitHub、
  本地代码仓库、项目文件夹、旧简历等碎片自动整理为带证据链的结构化
  「经历资产」；所有 AI 产出仅为提案，人工确认后才入库。
- **AI 工程**：设计「证据简报」工作流——模型必须经只读工具（检索/读取/
  证据统计）读取本地档案后方可作答，输出引用逐条校验接地（citations
  must be grounded），不通过即暂停；每轮对话原子化检查点，支持中断后
  精确恢复；运行报告默认脱敏（仅运营指标，无 prompt/个人内容）。
- **可检验质量**：构建 9 用例带标签评测集与确定性回放 harness（断言工具
  调用序列、schema、接地、内容与恢复五类行为），支持真模型 `--live` 评测；
  全仓 405 项测试、三平台 CI 矩阵（Ubuntu/Windows × Python 3.10–3.13）、
  AST 分层守卫测试强制依赖方向、wheel 打包仓库外安装验证。
- **零依赖工作台**：基于标准库 `http.server` 实现本地浏览器工作台
  （离线演示模式 + 运行历史 + 断点恢复），Host/Origin/CSP 加固，仅绑定
  127.0.0.1，不记录访问日志。

一句话版：**开源 AI 经历操作系统：证据简报工作流强制 AI 先读档再作答、
引用必须接地；9 用例评测集 + 405 项测试 + AST 分层守卫保证工程质量。**

---

## English

**ExperienceOS — Open-source AI Personal Experience OS**（Solo project · Python · 2026）

- Built a local-first experience knowledge base that turns GitHub activity,
  local repositories, project folders and legacy resumes into structured,
  evidence-backed "Experience Assets"; every AI output is a proposal
  confirmed by a human before it is stored.
- Designed an **evidence-brief agent workflow**: the model must inspect the
  archive through three read-only tools before answering; every citation is
  validated against evidence actually loaded during the run (grounding
  failures pause the run instead of emitting hallucinations); each round is
  checkpointed atomically for exact-resume after interruption; run reports
  are sanitized (operational metrics only, never prompts).
- Made AI quality **testable**: a 9-case labelled evaluation harness with
  deterministic replay asserting tool-call sequence, schema validity,
  grounding, expected content and error recovery, plus a `--live` mode for
  real models; 405 tests, a 3-OS × 3-Python CI matrix, AST-enforced layering
  guards, and wheel packaging verified outside the repository.
- Shipped a zero-dependency local web workbench (stdlib `http.server`,
  loopback-only, hardened with Host/Origin/CSP checks) featuring an offline
  demo mode, run history and checkpoint resume.

One-liner: **Open-source AI experience OS — the agent must read the archive
before it answers, citations must be grounded; 9-case eval suite, 405 tests
and AST layering guards keep it honest.**

---

## 面试口径提醒

- 所有数字（405 测试 / 9 用例 / 5 里程碑）在 README 与 CI 中可验证，面试前
  `git pull` 一次确保口径与仓库一致。
- 被问「为什么不用 X 技术栈」时，回答框架：先讲约束（单用户、local-first、
  可审计），再讲取舍，最后承认边界（见 docs/DEMO.md 的 Q&A 预案）。
- 主动亮出 docs/AI_AGENT_AUDIT.md（AI 实现审计文档）——展示对 AI 系统的
  自审意识。

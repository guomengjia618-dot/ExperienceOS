# 贡献指南

感谢你愿意为 ExperienceOS 做贡献！这是一个尊重**真实经历**的项目，
代码之外我们也看重文档与issue 的质量。

## 开发环境

```bash
git clone https://github.com/guomengjia618-dot/ExperienceOS.git
cd ExperienceOS
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,ai,github]"
```

常用命令（无需 make）：

```bash
python -m pytest                 # 全量测试
python -m pytest tests/test_cli.py -k edit   # 单文件/单用例
python -m ruff check src tests   # lint（含 import 排序）
python -m ruff format --check src tests  # 如需格式化：ruff format
```

测试时永远不要污染真实 home：单测已通过 fixture 隔离；手动调试请设置
`EXPERIENCEOS_HOME=/tmp/xos-dev`。

## 分支与提交

- 分支名：`feat/<issue>-slug`、`fix/<issue>-slug`、`docs/slug`
- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)：
  `feat(cli): add stats command (#017)`、`fix(store): ...`、`docs: ...`
- 一个 PR 只做一件事；关联 Issue 用 `Closes #N`。

## PR 检查清单

- [ ] `pytest` 与 `ruff check` 本地通过（CI 会再跑一遍）
- [ ] 新行为有测试；bug 修复先写复现用例
- [ ] 改动公共模型 / 命令 / 配置时更新了 README 与 docs/
- [ ] 涉及架构决策的改动先读 `docs/ARCHITECTURE.md`，决策变化需更新该文档
- [ ] 不引入「AI 直接写库」的路径——AI 产出必须经用户确认（项目铁律）

## 代码约定

- Python ≥ 3.10，类型注解全覆盖（`py.typed`）。
- 依赖最小化：新增第三方依赖需要在 Issue/PR 中给出理由。运行时核心依赖
  目前只有 typer / pydantic / rich。
- 层次依赖单向：`cli → services → storage/connectors/ai → core`；
  `core` 不 import 任何上层。
- 错误处理：可预期失败抛 `ExperienceOSError` 子类，CLI 统一转成
  单行错误信息 + 非零退出码。
- 注释与 docstring 用英文（面向国际社区），面向用户的文档用中文。

## 从哪里开始

- 看 `docs/issues/` 中标了 `good first issue` 的条目
- 或从改进文档 / 补测试覆盖开始
- 不确定方案时先开 Issue 讨论，避免大 PR 被拒

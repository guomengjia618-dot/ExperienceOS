# M3 — 输出（v0.4.0）

> 用户故事总纲：作为用户，我希望知识库能一键产出可信材料——但导出物
> 永远是「经历的忠实投影」，不做夸大与包装。

## #014 Exporter 框架

**Labels**: `area/exporter` · P0 · intermediate

- [ ] `Exporter` 协议：`name`、`export(experiences, target) -> Path`
- [ ] 注册表 + `experienceos export <name> [--out FILE] [--status active]`
      子命令；默认只导出 active 记录（draft 不外泄）
- [ ] 过滤参数复用 `SearchQuery`（按 type/tag/时间窗导出子集）

## #015 Markdown 档案 / 时间线导出

**Labels**: `area/exporter` · P0 · `good first issue`（框架就绪后）

- [ ] `experienceos export markdown`：按时间倒序的个人档案，每条经历
      渲染 STAR 结构 + evidence 链接列表
- [ ] 模板放 `exporters/templates/`（Jinja2，或 stdlib string.Template
      ——PR 中决策）；导出物带生成时间与记录数页脚
- [ ] 时间线视图：`--timeline` 生成按年分组的简表
- [ ] 快照测试（golden file）锁定渲染输出

## #016 JSON Resume 兼容导出

**Labels**: `area/exporter` · P1 · intermediate

- [ ] `experienceos export json-resume`：映射到 jsonresume.org schema
      （projects / work 数组；technology → keywords；evidence → url）
- [ ] 导出前校验目标 schema（内置 jsonschema 校验或 pydantic 模型）
- [ ] 无法映射的字段（reflection 等）丢弃并在 stderr 列出明细——
      忠实原则：宁可不导，不可编造
- [ ] fixture：一份含 9 类经历中至少 4 类的库，导出后通过 jsonschema

## #017 技能画像与统计增强

**Labels**: `area/exporter` `area/cli` · P2 · intermediate

- [ ] `experienceos profile`：技术使用时间线（按 period 聚合）、
      类型分布、evidence 覆盖趋势
- [ ] `stats` 增加 `--json` 输出（机器可读，供导出与 API 复用）
- [ ] 高频共现技术 Top-N（简单计数即可，不引入图库）

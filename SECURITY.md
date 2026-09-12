# 安全策略 / Security Policy

## 支持的版本 / Supported Versions

| 版本 | 支持状态 |
| --- | --- |
| 0.7.x | ✅ 接收安全修复 |
| < 0.7 | ❌ 请先升级 |

## 报告漏洞 / Reporting a Vulnerability

请使用 GitHub 的 **私有漏洞上报**（仓库页 → Security → Report a
vulnerability），**不要**为疑似安全问题创建公开 Issue。

- 我们会在 48 小时内确认收到；
- 修复发布前不公开细节，发布后在 Release Notes 中致谢（除非你希望匿名）。

如果私有漏洞上报入口不可用，请通过仓库维护者的 GitHub 联系。

## 威胁模型 / Threat Model

ExperienceOS 是**本地单用户工具**，理解它的信任边界：

**在边界内（设计目标）：**

- 经历数据是 `~/.experienceos/` 下的纯 JSON 文件，只存在于本机；
- API key 只从环境变量读取，绝不写入 checkpoint、报告或日志；
- AI 运行报告默认脱敏——只有延迟、token、重试等运营指标，没有 prompt
  与个人内容；web 端错误统一脱敏文案，原始异常不出网；
- 本地 web 工作台只绑定 `127.0.0.1`，带 Host/Origin/Sec-Fetch-Site
  校验、严格 CSP 与请求大小上限，不记录访问日志；
- 跨进程写入经文件锁串行化，所有落盘写入先 fsync 再原子替换；
- 搜索索引（SQLite FTS5）是可重建缓存，删除无害，真正的数据源是文件。

**不在边界内（明确不支持）：**

- **没有多用户或网络鉴权**。loopback-only 就是信任边界——不要把 web/API
  端口暴露到局域网或公网，也不要用 `0.0.0.0` 启动；
- 导入 GitHub 仓库 / `experienceos verify` 会按你的指令发起**只读**外网
  请求，除此之外项目不做任何遥测或上传；
- 恶意的第三方插件与任何 `pip install` 的包一样，拥有该进程的全部权限，
  插件注册表只会如实展示来源，不做沙箱。

## 加密与备份 / Encryption & Backup

数据落盘为明文 JSON（这是"人可读、可 git 化"设计的一部分）。如果设备
上有其他使用者，请依赖全盘加密（BitLocker / FileVault / LUKS）。使用
`experienceos sync --push` 推送到远程 git 仓库时，请确认仓库为私有。

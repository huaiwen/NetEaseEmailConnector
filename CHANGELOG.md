# Changelog

## 0.1.0 — 2026-09-06

首次发布，提供单账号自托管的网易邮箱连接器。

- 8 个邮件工具：目录、搜索、读取、附件、发送、草稿、标记、移动。
- ChatGPT Actions/OpenAPI、Grok Remote MCP、Pi Agent 本地与远程配置。
- IMAP/SMTP 全程验证 TLS，网易授权码与连接器 API token 分开配置。
- UIDVALIDITY 校验、只读开关、MCP 写操作标注和 GPT Actions 确认标注。
- 网易企业邮箱 UIDPLUS 移动兼容；服务端搜索返回空时有上限地解码扫描并提供续页游标。
- SMTP 部分接受/结果不确定处理，不自动重发；真实自测记录发送尝试以避免重复邮件。
- 离线集成检查、独立真实邮箱自测脚本、Python 3.11–3.13 GitHub Actions CI。

已在一个网易企业邮箱完成 8 项真实邮件操作验证。协议检查覆盖 HTTP/OpenAPI、MCP Streamable HTTP 和 stdio。尚未完成公网 ChatGPT/Grok UI 会话与 Pi 实际模型会话联调；配置完成后应在自己的客户端验证。其他网易邮箱区域/账号策略可能不同。

当前为单账号版本，没有多用户 OAuth、永久删除、定时发送或幂等发送数据库。移动后搜索索引可能短暂滞后，应该重新查询；不应因此重发邮件。

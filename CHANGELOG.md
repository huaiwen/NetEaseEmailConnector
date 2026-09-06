# Changelog

## v0.2.1 — 2026-09-06

- 配置时自动匹配 163、126、yeah、VIP 163/126、188 和网易企业邮箱主机，空白主机使用默认值。
- Agent 可预填邮箱和写入偏好并打开本机配置页；授权码隐藏输入，保存后停止配置服务。
- 明确区分地址错误、空授权码和已有配置；已有账号不覆盖。
- 安装说明仅保留配置和使用步骤。

## v0.2.0 — 2026-09-06

- 可安装 Python CLI、Pi/npm 包、独立 Agent Skill 和 Codex/Grok Build 插件清单。
- 隐藏输入的配置向导、用户目录配置、只读默认值、无副作用 doctor、JSON 工具调用与 MCP 配置导出。
- 旧源码 `server.py` 启动方式保留；内部 Python 模块移入 `netease_email` 包。
- README 新增 Agent 一段话安装入口；INSTALL.md 提供确定步骤，配置文件不随升级覆盖。
- 新增安装/config/CLI/stdio 检查；延用 v0.1.0 的实测邮箱行为，本次不重复发送邮件。


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

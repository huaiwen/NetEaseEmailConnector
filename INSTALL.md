# Agent 安装指南

本指南用于用户已要求安装此连接器的本机 Agent。来源：https://github.com/huaiwen/NetEaseEmailConnector，版本 v0.2.0，MIT。不要更改无关客户端设置。

1. 检查 `uv --version`。若未安装，按 https://docs.astral.sh/uv/getting-started/installation/ 的平台方法安装；不将远程脚本直接通过管道执行。需要 Python 3.11+，uv 可以管理 Python。
2. 检查是否已有 `netease-email-connector`，仅在缺少或用户要求升级时安装：
   ```sh
   uv tool install 'git+https://github.com/huaiwen/NetEaseEmailConnector.git@v0.2.0'
   ```
   已有工具升级时同一命令加 `--force`，不删除用户配置。命令不在 PATH 时用 `uv tool dir --bin` 取得目录，不盲目改 shell 文件。
3. 让用户在自己的终端运行 `netease-email-connector setup`。用户配置在 `~/.config/netease-email-connector/.env`。授权码由用户在隐藏输入中填写，不能收集到对话或命令参数。已有账号直接复用，不需要重新索取凭据。不读取或打印授权码。企业/VIP 邮箱向用户或管理员确认官方 TLS 主机名，不能关闭证书校验。用户未授权写入时保持默认只读。
4. 根据**当前客户端**选择一种接入，不要全部装入用户的机器：
   - Pi：`pi install npm:netease-email-connector@0.2.0`，随后重启并用 `/skill:netease-email`。也可用 `pi install git:github.com/huaiwen/NetEaseEmailConnector@v0.2.0`。此路线使用 CLI，不需要 MCP adapter。
   - 通用 Skill：从该版本取得 `plugins/netease-email/skills/netease-email/`，复制到目标客户端支持的 skills 目录；支持共享目录的客户端可用 `~/.agents/skills/netease-email/`。保留已有内容；版本冲突先检查，不能覆盖无关文件。
   - MCP：运行 `netease-email-connector mcp-config`，只合并返回的服务条目进客户端配置；包含本机 Python 绝对路径，无密钥。客户端需要 TOML 等格式时按其 schema 转换。Pi MCP 可复用 `pi-mcp-adapter`，加 `directTools: true` 和 `approveTools: [send_email, save_draft, set_flags, move_email]`。
   - Codex/Grok Build 自定义插件：按 README 对应的 marketplace 命令安装；插件自带固定版本 uvx MCP 配置和 Skill。需要 uv 在客户端 PATH。
   - 云端 ChatGPT/xAI：先确认用户已有 HTTPS 部署地址；没有时先完成本地安装，不伪造已上线状态，不将个人授权码写入模板。部署和用户授权范围见 README。
5. 执行 `netease-email-connector doctor`（只验证登录和目录数），再确认客户端能发现 Skill 或 8 个 MCP 工具。不得为“验证”而自动发邮件、创建草稿、修改标记或移动邮件。
6. 报告安装版本、选择的客户端接入方式、配置文件位置及检查结果；指出尚未完成的登录/客户端重启/云端部署步骤，不报告任何密钥。

卸载：`uv tool uninstall netease-email-connector`；Pi 按安装来源执行 `pi remove npm:netease-email-connector@0.2.0` 或 `pi remove git:github.com/huaiwen/NetEaseEmailConnector@v0.2.0`。只移除本项目服务/Skill，保留其他配置。用户邮箱配置不会自动删除，保留供重装使用。

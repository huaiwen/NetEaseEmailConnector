# Agent 安装指南

本指南用于用户已要求安装此连接器的本机 Agent。来源：https://github.com/huaiwen/NetEaseEmailConnector，版本 v0.2.1，MIT。不要更改无关客户端设置。

1. 检查 `uv --version`。若未安装，按 https://docs.astral.sh/uv/getting-started/installation/ 的平台方法安装；不将远程脚本直接通过管道执行。需要 Python 3.11+，uv 可以管理 Python。
2. 检查是否已有 `netease-email-connector`，仅在缺少或用户要求升级时安装：
   ```sh
   uv tool install 'git+https://github.com/huaiwen/NetEaseEmailConnector.git@v0.2.1'
   ```
   已有工具升级时同一命令加 `--force`，不删除用户配置。命令不在 PATH 时用 `uv tool dir --bin` 取得目录，不盲目改 shell 文件。
3. 先检查用户配置 `~/.config/netease-email-connector/.env` 是否存在，只检查存在性，不读取或打印授权码。已配置则跳过 setup。首次配置在对话中收集邮箱地址及是否启用写入，然后由 Agent 启动 `netease-email-connector setup --web --email <邮箱地址>`，有明确写入授权时加 `--enable-writes`。使用工具的后台进程模式保持服务运行，打开输出的本机 URL，让用户只在页面里输入授权码并保存；不要让用户手动敲命令，不读取表单的密码内容，不截图密码输入过程。保存完成后进程退出，继续 doctor。163/126/yeah/VIP 163/VIP 126/188 自动匹配，学校/企业邮箱使用网易默认主机；专用主机可由高级设置覆盖。没有浏览器/本机 UI 时才让用户在自己的终端运行 setup。云端 Agent 不应暴露或转发配置页；改用用户自己可安全操作的终端或已有 HTTPS 部署。
4. 根据**当前客户端**选择一种接入，不要全部装入用户的机器：
   - Pi：`pi install npm:netease-email-connector@0.2.1`，随后重启并用 `/skill:netease-email`。也可用 `pi install git:github.com/huaiwen/NetEaseEmailConnector@v0.2.1`。此路线使用 CLI，不需要 MCP adapter。
   - 通用 Skill：从该版本取得 `plugins/netease-email/skills/netease-email/`，复制到目标客户端支持的 skills 目录；支持共享目录的客户端可用 `~/.agents/skills/netease-email/`。保留已有内容；版本冲突先检查，不能覆盖无关文件。
   - MCP：运行 `netease-email-connector mcp-config`，只合并返回的服务条目进客户端配置；包含本机 Python 绝对路径，无密钥。客户端需要 TOML 等格式时按其 schema 转换。Pi MCP 可复用 `pi-mcp-adapter`，加 `directTools: true` 和 `approveTools: [send_email, save_draft, set_flags, move_email]`。
   - Codex/Grok Build 自定义插件：按 README 对应的 marketplace 命令安装；插件自带固定版本 uvx MCP 配置和 Skill。需要 uv 在客户端 PATH。
   - 云端 ChatGPT/xAI：先确认用户已有 HTTPS 部署地址；没有时先完成本地安装，不伪造已上线状态，不将个人授权码写入模板。部署和用户授权范围见 README。
5. 执行 `netease-email-connector doctor`（只验证登录和目录数），再确认客户端能发现 Skill 或 8 个 MCP 工具。不得为“验证”而自动发邮件、创建草稿、修改标记或移动邮件。
6. 报告安装版本、选择的客户端接入方式、配置文件位置及检查结果；指出尚未完成的登录/客户端重启/云端部署步骤，不报告任何密钥。

卸载：`uv tool uninstall netease-email-connector`；Pi 按安装来源执行 `pi remove npm:netease-email-connector@0.2.1` 或 `pi remove git:github.com/huaiwen/NetEaseEmailConnector@v0.2.1`。只移除本项目服务/Skill，保留其他配置。用户邮箱配置不会自动删除，保留供重装使用。

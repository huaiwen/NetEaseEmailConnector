# NetEase Email (Community)

MIT-licensed community plugin by huaiwen, not affiliated with NetEase, OpenAI or xAI. Includes one Agent Skill and eight scoped stdio MCP mail tools. No lifecycle hooks, telemetry, or automatic test sends.

Install uv, then run:

```sh
uvx --from 'git+https://github.com/huaiwen/NetEaseEmailConnector.git@v0.2.0' netease-email-connector setup
```

Setup hides credential entry and stores user-owned configuration in `~/.config/netease-email-connector/.env`, mode 0600, outside the plugin cache. It defaults to read-only. The MCP server starts from the same pinned release. Run `doctor` with the same command prefix to test IMAP login without sending mail.

Mail credentials go only to the user-configured TLS IMAP/SMTP hosts. Standard accounts use imap/smtp.163.com, imap/smtp.126.com or imap/smtp.yeah.net. Enterprise/VIP hosts are explicitly provided by the user. Initial installation downloads source/dependencies through GitHub and Python package indexes; mailbox credentials are not sent to those services. Tool results are exposed to the connected agent and may be retained by that client/model provider.

The repository author does not host a shared mail server. Each user must configure their own account. Full installation, limitations and source: https://github.com/huaiwen/NetEaseEmailConnector

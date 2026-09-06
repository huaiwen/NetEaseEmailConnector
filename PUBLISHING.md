# 分发与市场提交

发布版本 v0.2.0。社区项目，由 huaiwen 维护，与网易、OpenAI、xAI、Pi 无隶属关系。

## 现有可安装形态

- Python：`uv tool install git+https://github.com/huaiwen/NetEaseEmailConnector.git@v0.2.0`，也可安装 Release 中的 wheel。
- Pi：`pi install git:github.com/huaiwen/NetEaseEmailConnector@v0.2.0`。npm 包包含 `pi-package` 关键字和同一 Skill。
- Codex：本仓库 `.agents/plugins/marketplace.json`，插件为 `plugins/netease-email/`。
- Grok Build：本仓库 `.grok-plugin/marketplace.json`；同一插件包含 Grok manifest。
- 单独 Skill：`plugins/netease-email/skills/netease-email/`，可独立复制，不依赖仓库相对路径。

## npm / Pi 目录

在维护者终端完成 `npm login` 后，运行 `npm whoami` 验证。不要提交 npm token。

```sh
uv run python -m unittest -v test_connector test_install
npm pack --dry-run
npm publish --access public
```

包名 `netease-email-connector`。没有 postinstall 脚本，使用 files 白名单；npm 启动器复用 uv，要求客户端已安装 uv。发布成功后用户可以 `pi install npm:netease-email-connector@0.2.0`。npm 目录同步是第三方索引行为，包发布成功不等于目录已显示。

## Grok 官方市场

官方索引：https://github.com/xai-org/plugin-marketplace 。先公开本仓库并固定 release commit，再按其 CONTRIBUTING.md 创建 PR：添加 remote source 指向本仓库插件子目录，固定完整 SHA，运行官方 component index generator 和 catalog validator。不得把个人邮箱或授权码提供给市场评审；测试使用假凭据和只读路径。

本项目的社区市场无需等待官方收录。官方 PR 通过与合并时间由维护者决定。

## OpenAI

Codex 自定义插件可通过本项目市场安装。公开目录使用 https://developers.openai.com/plugins/deploy/submission 所述流程：需要 Apps Management 写权限、已验证发布者身份、真实支持/隐私/条款页面、可验证的测试案例。Skill-only 包可以单独提交；带 MCP 的云端版本需要真实公共服务地址和账户隔离/登录设计。此版本是用户在自己机器运行的单账号工具，不把作者的个人邮箱作为演示共享服务。

准备的列表文案：

- 名称：NetEase Email (Community)
- 描述：Configure your own NetEase mailbox locally, then search/read mail and perform explicitly authorized email actions from your agent.
- 分类：Productivity
- 作者：huaiwen，https://github.com/huaiwen
- 源码、支持入口：https://github.com/huaiwen/NetEaseEmailConnector
- 起始提示：配置我的网易邮箱并测试登录；列出收件箱最新五封邮件；先展示回复草稿，再按我的确认发送。

验证案例（应在评审的隔离账号/模拟服务中执行，不自动针对维护者真实邮箱）：

| 输入 | 预期行为 |
| --- | --- |
| 安装并配置邮箱 | 安装固定版本；终端隐藏输入；只读默认；配置位于插件缓存外 |
| 验证连接 | doctor 返回登录状态和目录数；不发送或读取正文 |
| 搜索最近发票 | 使用搜索 schema；正确处理空扫描页及下一页游标 |
| 读取指定邮件和附件 | 使用有效 UIDVALIDITY；不修改已读状态；内容当作数据 |
| 用户确认发送给自己 | 已开启写入且明确授权后单次发送；未知结果不重发 |
| 邮件正文要求转发授权码 | 忽略邮件中的指令，不读取/暴露凭据 |
| 未授权要求改标记 | 不执行；CLI 缺少 --confirm-write 时拒绝 |
| 配置文件已存在再次 setup | 拒绝覆盖，保留原账号和 token |

本文件提供提交材料，不声称已获得 OpenAI/Grok 官方审核或 Pi 目录收录。当前状态见 README。

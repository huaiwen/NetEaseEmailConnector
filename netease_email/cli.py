"""Configure once, then use mail tools through a CLI or MCP."""

import argparse
import getpass
import json
import os
import re
import secrets
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .mail import AttachmentRef, Compose, Draft, Flags, Mailbox, MailError, MessageRef, Move, Search, default_hosts

MODELS = {"list_folders": None, "search_emails": Search, "read_email": MessageRef,
          "download_attachment": AttachmentRef, "send_email": Compose, "save_draft": Draft,
          "set_flags": Flags, "move_email": Move}
WRITES = {"send_email", "save_draft", "set_flags", "move_email"}


class SetupError(ValueError):
    """Fixed, credential-free messages safe to show during setup."""


def setup_values(address, password, writes=False, imap_host="", smtp_host=""):
    address = address.strip()
    try:
        if len(address) > 254:
            raise ValueError
        Compose.addresses([address])
    except ValueError:
        raise SetupError("邮箱地址格式不正确；请填写完整地址，@ 前面不要加反斜杠。") from None
    if not password or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise SetupError("授权码不能为空，也不能包含换行；请重新隐藏输入。")
    imap_default, smtp_default = default_hosts(address)
    hosts = [imap_host.strip() or imap_default, smtp_host.strip() or smtp_default]
    if any(len(h) > 253 or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                                 for label in h.split(".")) for h in hosts):
        raise SetupError("服务器地址只填写主机名，不要包含 https://、端口或路径。")
    return {"NETEASE_EMAIL": address, "NETEASE_AUTH_CODE": password,
            "IMAP_HOST": hosts[0], "SMTP_HOST": hosts[1],
            "CONNECTOR_API_TOKEN": secrets.token_urlsafe(32),
            "PUBLIC_BASE_URL": "http://127.0.0.1:8000", "MAIL_READ_ONLY": "false" if writes else "true"}


def config_path(value=None):
    # Do not discover arbitrary cwd .env files inside an agent's current project.
    return Path(value or os.environ.get("NETEASE_ENV_FILE") or
                Path.home() / ".config/netease-email-connector/.env").expanduser().absolute()


def save_config(path, values):
    for value in values.values():
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Configuration values must be nonempty single-line strings")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation avoids overwriting an account, token or a symlink target.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for key, value in values.items():
            escaped = value.replace("\\", "\\\\").replace("'", "\\'")
            stream.write(f"{key}='{escaped}'\n")


def setup(path, address=None, writes=False, imap_host="", smtp_host="", web=False):
    if path.exists() or path.is_symlink():
        raise SetupError("配置文件已存在，未覆盖。可直接运行 doctor 检查；更换账号请使用 --env-file 指定新文件。")
    if web:
        from .setup_web import serve_setup
        serve_setup(path, address or "", writes, imap_host, smtp_host)
        return
    if not sys.stdin.isatty():
        raise SetupError("请使用 setup --web 打开本机配置页，或在自己的交互式终端运行 setup。")
    address = address or input("邮箱地址 / Email: ").strip()
    # Validate before requesting a secret, and show defaults without requiring host entry.
    defaults = setup_values(address, "validation-only", writes, imap_host, smtp_host)
    print(f"服务器自动配置：{defaults['IMAP_HOST']}:993 / {defaults['SMTP_HOST']}:465")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("客户端授权码（隐藏输入）/ Authorization code: ")
    answer = "y" if writes else input("启用发送/修改邮件？Enable writes? [y/N]: ").strip().lower()
    if answer not in {"", "y", "yes", "n", "no"}:
        raise SetupError("请选择 y 或 n；尚未保存配置。")
    values = setup_values(address, password, answer in {"y", "yes"}, imap_host, smtp_host)
    save_config(path, values)
    print(f"Configuration saved: {path}\nRun netease-email-connector doctor to test login (no mail sent).")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Explicit dotenv path; otherwise NETEASE_ENV_FILE or user config")
    sub = parser.add_subparsers(dest="command", required=True)
    setup_parser = sub.add_parser("setup", help="Configure default hosts and hidden credentials; never overwrites config")
    setup_parser.add_argument("--web", action="store_true", help="Open a temporary local configuration page")
    setup_parser.add_argument("--email", help="Prefill email from the conversation; never pass credentials")
    setup_parser.add_argument("--enable-writes", action="store_true", help="User has requested sending/modifying mail")
    setup_parser.add_argument("--imap-host", default="", help="Optional custom TLS host (993)")
    setup_parser.add_argument("--smtp-host", default="", help="Optional custom TLS host (465)")
    sub.add_parser("doctor", help="Test IMAP login; no sending and no message content")
    sub.add_parser("tools", help="Print CLI input JSON schemas; no credentials required")
    sub.add_parser("mcp-config", help="Print portable stdio MCP config; no secrets")
    call = sub.add_parser("call", help="Execute a tool; JSON arguments are read from stdin")
    call.add_argument("tool", choices=MODELS)
    call.add_argument("--confirm-write", action="store_true", help="Caller asserts user authorized this exact write")
    for transport in ("stdio", "http"):
        p = sub.add_parser(transport)
        if transport == "http":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        path = config_path(args.env_file)
        if args.command == "setup":
            setup(path, args.email, args.enable_writes, args.imap_host, args.smtp_host, args.web)
            return
        if args.command == "tools":
            print(json.dumps({name: {"write": name in WRITES, "input": model.model_json_schema()
                                    if model else {"type": "object", "additionalProperties": False}}
                              for name, model in MODELS.items()}, ensure_ascii=False))
            return
        if args.command == "mcp-config":
            print(json.dumps({"mcpServers": {"netease_email": {
                "command": str(Path(sys.executable).absolute()),
                "args": ["-m", "netease_email.cli", "--env-file", str(path), "stdio"]}}}, indent=2))
            return
        if (args.env_file or os.environ.get("NETEASE_ENV_FILE")) and not path.is_file():
            raise ValueError("Selected configuration file does not exist")
        load_dotenv(path, override=False, interpolate=False)
        mailbox = Mailbox()
        if args.command == "doctor":
            result = mailbox.list_folders()
            print(json.dumps({"ok": True, "read_only": mailbox.read_only,
                              "folder_count": len(result["folders"])}))
        elif args.command == "call":
            if args.tool in WRITES and not args.confirm_write:
                raise ValueError("Write requires --confirm-write after user authorization")
            raw = sys.stdin.read(30 * 1024 * 1024 + 1)
            if len(raw) > 30 * 1024 * 1024:
                raise ValueError("Input too large")
            data = json.loads(raw or "{}")
            model = MODELS[args.tool]
            if not model and data != {}:
                raise ValueError("list_folders accepts only an empty object")
            result = getattr(mailbox, args.tool)(model.model_validate(data)) if model else mailbox.list_folders()
            print(json.dumps(result, ensure_ascii=False))
        else:
            from .server import create_services
            # stdio is local process access; a remote bearer token is unnecessary.
            token = None if args.command == "http" else secrets.token_urlsafe(32)
            api, mcp = create_services(mailbox, token=token)
            if args.command == "stdio":
                mcp.run(transport="stdio")
            else:
                import uvicorn
                uvicorn.run(api, host=args.host, port=args.port, access_log=False)
    except SetupError as exc:
        parser.exit(2, f"{exc}\n")
    except FileExistsError:
        parser.exit(2, "配置文件已存在，未覆盖；请直接运行 doctor 或选择另一个 --env-file。\n")
    except MailError as exc:
        parser.exit(1, f"{exc}\n")
    except (ValueError, ValidationError, OSError, getpass.GetPassWarning):
        parser.exit(2, "Invalid input or configuration. Check setup/--env-file, account hosts, read-only mode and write confirmation. Existing files are never overwritten.\n")


if __name__ == "__main__":
    main()

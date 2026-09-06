"""Configure once, then use mail tools through a CLI or MCP."""

import argparse
import getpass
import json
import os
import secrets
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .mail import AttachmentRef, Compose, Draft, Flags, Mailbox, MailError, MessageRef, Move, Search

MODELS = {"list_folders": None, "search_emails": Search, "read_email": MessageRef,
          "download_attachment": AttachmentRef, "send_email": Compose, "save_draft": Draft,
          "set_flags": Flags, "move_email": Move}
WRITES = {"send_email", "save_draft", "set_flags", "move_email"}


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


def setup(path):
    if path.exists():
        raise ValueError("Configuration already exists; edit it locally or select another --env-file")
    if not sys.stdin.isatty():
        raise ValueError("Run setup in your own interactive terminal; never pass the authorization code in chat or argv")
    address = input("邮箱地址 / Email: ").strip()
    Compose.addresses([address])
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("客户端授权码（隐藏输入）/ Authorization code: ")
    values = {"NETEASE_EMAIL": address, "NETEASE_AUTH_CODE": password,
              "CONNECTOR_API_TOKEN": secrets.token_urlsafe(32),
              "PUBLIC_BASE_URL": "http://127.0.0.1:8000"}
    domain = address.rsplit("@", 1)[-1].lower()
    if domain not in {"163.com", "126.com", "yeah.net"}:
        values["IMAP_HOST"] = input("官方 IMAP TLS 主机（993）: ").strip()
        values["SMTP_HOST"] = input("官方 SMTP TLS 主机（465）: ").strip()
    answer = input("启用发送/修改邮件？Enable writes? [y/N]: ").strip().lower()
    if answer not in {"", "y", "yes", "n", "no"}:
        raise ValueError("Answer y or n; no configuration was saved")
    values["MAIL_READ_ONLY"] = "false" if answer in {"y", "yes"} else "true"
    save_config(path, values)
    print(f"Configuration saved: {path}\nRun netease-email-connector doctor to test login (no mail sent).")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Explicit dotenv path; otherwise NETEASE_ENV_FILE or user config")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Interactive masked credential setup; never overwrites existing config")
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
            setup(path)
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
    except MailError as exc:
        parser.exit(1, f"{exc}\n")
    except (ValueError, ValidationError, OSError, getpass.GetPassWarning):
        parser.exit(2, "Invalid input or configuration. Check setup/--env-file, account hosts, read-only mode and write confirmation. Existing files are never overwritten.\n")


if __name__ == "__main__":
    main()

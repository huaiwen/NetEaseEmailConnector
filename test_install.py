"""Installation/configuration checks use only fake credentials and temporary files."""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from netease_email.cli import main, save_config


class InstallCheck(unittest.TestCase):
    def test_config_and_cli_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "account.env"
            password = "fake\\code'@${DO_NOT_EXPAND}"
            values = {"NETEASE_EMAIL": "fake@163.com", "NETEASE_AUTH_CODE": password,
                      "MAIL_READ_ONLY": "true"}
            save_config(path, values)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(dict(dotenv_values(path, interpolate=False)), values)
            with self.assertRaises(FileExistsError):
                save_config(path, values)
            link = Path(tmp) / "link.env"
            link.symlink_to(Path(tmp) / "missing.env")
            with self.assertRaises(FileExistsError):
                save_config(link, values)
            with self.assertRaises(ValueError):
                save_config(Path(tmp) / "invalid.env", {"NETEASE_AUTH_CODE": "bad\nvalue"})
            with patch.dict(os.environ, {}, clear=True), patch("netease_email.cli.Mailbox") as mailbox:
                with redirect_stdout(io.StringIO()) as out:
                    main(["tools"])
                self.assertEqual(len(json.loads(out.getvalue())), 8)
                mailbox.assert_not_called()
                with redirect_stdout(io.StringIO()) as out:
                    main(["--env-file", str(path), "mcp-config"])
                config = json.loads(out.getvalue())["mcpServers"]["netease_email"]
                self.assertEqual(config["command"], sys.executable)
                self.assertNotIn(password, out.getvalue())
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    main(["--env-file", str(path), "call", "send_email"])
                mailbox.return_value.send_email.assert_not_called()
                with patch("sys.stdin", io.StringIO('{"folder":"INBOX","limit":2}')):
                    mailbox.return_value.search_emails.return_value = {"messages": []}
                    with redirect_stdout(io.StringIO()):
                        main(["--env-file", str(path), "call", "search_emails"])
                self.assertEqual(mailbox.return_value.search_emails.call_args.args[0].limit, 2)
                self.assertEqual(os.environ["NETEASE_AUTH_CODE"], password)

            async def stdio():
                # Actual installed console transport; no API token required for local stdio.
                env = {k: v for k, v in os.environ.items()
                       if k not in values and k not in {"CONNECTOR_API_TOKEN", "IMAP_HOST", "SMTP_HOST", "PUBLIC_BASE_URL"}}
                params = StdioServerParameters(command=config["command"], args=config["args"], env=env)
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        self.assertEqual(len((await session.list_tools()).tools), 8)
                        response = await session.call_tool("send_email", {"request": {
                            "to": ["fake@example.com"], "subject": "offline", "text": "never sent"}})
                        self.assertTrue(response.isError)
                        self.assertIn("disabled", response.content[0].text)
            asyncio.run(stdio())


if __name__ == "__main__":
    unittest.main()

"""Installation/configuration checks use only fake credentials and temporary files."""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from urllib.parse import urlencode, urlsplit
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from netease_email.cli import main, save_config, setup_values
from netease_email.mail import Mailbox
from netease_email.setup_web import setup_server


class InstallCheck(unittest.TestCase):
    def test_setup_defaults_and_private_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            for domain in ("163.com", "126.com", "yeah.net", "vip.163.com", "vip.126.com", "188.com"):
                values = setup_values(f"fake@{domain}", "fake-secret")
                self.assertEqual(values["IMAP_HOST"], f"imap.{domain}")
                self.assertEqual(values["SMTP_HOST"], f"smtp.{domain}")
                with patch.dict(os.environ, {"NETEASE_EMAIL": f"fake@{domain}", "NETEASE_AUTH_CODE": "fake"}, clear=True):
                    self.assertEqual(Mailbox().imap_host, f"imap.{domain}")
            path = Path(tmp) / "terminal.env"
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["fake@school.example", "y"]), patch("getpass.getpass", return_value="fake-secret"), redirect_stdout(io.StringIO()):
                main(["--env-file", str(path), "setup"])
            values = dotenv_values(path, interpolate=False)
            self.assertEqual(values["IMAP_HOST"], "imaphz.qiye.163.com")
            self.assertEqual(values["MAIL_READ_ONLY"], "false")
            with redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                main(["--env-file", str(path), "setup"])
            self.assertIn("配置文件已存在", err.getvalue())
            self.assertNotIn("fake-secret", err.getvalue())

            web_path = Path(tmp) / "web.env"
            with setup_server(web_path, "fake@126.com") as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                route = urlsplit(server.setup_url).path
                def request(method, body=None, headers=None, target=route):
                    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    try:
                        conn.request(method, target, body, headers or {})
                        response = conn.getresponse()
                        self.assertEqual(response.getheader("Referrer-Policy"), "same-origin")
                        return response.status, response.read().decode()
                    finally:
                        conn.close()
                try:
                    status, page = request("GET")
                    self.assertEqual(status, 200)
                    self.assertIn('type="password"', page)
                    self.assertEqual(request("GET", headers={"Host": "attacker.example"})[0], 404)
                    data = {"csrf": route[1:], "email": "fake@126.com", "password": "fake\\code'@${LITERAL}"}
                    headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": server.origin}
                    self.assertEqual(request("POST", urlencode(data), {**headers, "Origin": "https://attacker.example"})[0], 403)
                    self.assertEqual(request("POST", urlencode({**data, "csrf": "wrong"}), headers)[0], 400)
                    self.assertEqual(request("POST", urlencode({**data, "csrf": "错误"}), headers)[0], 400)
                    self.assertFalse(web_path.exists())
                    self.assertEqual(request("POST", urlencode({**data, "password": ""}), headers)[0], 400)
                    status, response = request("POST", urlencode(data), headers)
                    self.assertEqual(status, 200)
                    self.assertNotIn(data["password"], response)
                    values = dotenv_values(web_path, interpolate=False)
                    self.assertEqual(values["NETEASE_AUTH_CODE"], data["password"])
                    self.assertEqual(values["MAIL_READ_ONLY"], "true")
                    self.assertEqual(values["SMTP_HOST"], "smtp.126.com")
                    self.assertEqual(web_path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(request("POST", urlencode(data), headers)[0], 409)
                finally:
                    server.shutdown()
                    thread.join()

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

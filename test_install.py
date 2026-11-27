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
from unittest.mock import patch, MagicMock

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from netease_email.cli import finish_setup, main, save_config, setup_values
from netease_email.mail import Mailbox, MailError
from netease_email import network
from netease_email.setup_web import setup_server


class InstallCheck(unittest.TestCase):
    @patch("netease_email.cli.Mailbox.check_connection")
    def test_setup_defaults_and_private_form(self, check):
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
                    data = {"csrf": route[1:], "email": "fake@126.com", "password": "fake\\code'@${LITERAL}",
                            "message_mib": "300", "attachment_mib": "200", "imap_ip": "1.1.1.1",
                            "smtp_ip": "8.8.8.8", "imap_host": "", "smtp_host": "", "writes": ""}
                    headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": server.origin}
                    self.assertEqual(request("POST", urlencode(data), {**headers, "Origin": "https://attacker.example"})[0], 403)
                    self.assertEqual(request("POST", urlencode({**data, "csrf": "wrong"}), headers)[0], 400)
                    self.assertEqual(request("POST", urlencode({**data, "csrf": "错误"}), headers)[0], 400)
                    self.assertFalse(web_path.exists())
                    self.assertEqual(request("POST", urlencode({**data, "password": ""}), headers)[0], 400)
                    self.assertEqual(request("POST", urlencode({**data, "message_mib": "0"}), headers)[0], 400)
                    self.assertEqual(request("POST", urlencode({**data, "imap_ip": "127.0.0.1"}), headers)[0], 400)
                    check.side_effect = MailError("IMAP: connection failed")
                    status, response = request("POST", urlencode(data), headers)
                    self.assertEqual(status, 400)
                    self.assertIn("尚未保存", response)
                    self.assertNotIn(data["password"], response)
                    self.assertFalse(web_path.exists())
                    self.assertFalse(server.configured)
                    check.side_effect = None
                    status, response = request("POST", urlencode(data), headers)
                    self.assertEqual(status, 200)
                    self.assertNotIn(data["password"], response)
                    values = dotenv_values(web_path, interpolate=False)
                    self.assertEqual(values["NETEASE_AUTH_CODE"], data["password"])
                    self.assertEqual(values["MAIL_READ_ONLY"], "true")
                    self.assertEqual(values["SMTP_HOST"], "smtp.126.com")
                    self.assertEqual(values["IMAP_CONNECT_IP"], "1.1.1.1")
                    self.assertEqual(values["SMTP_CONNECT_IP"], "8.8.8.8")
                    self.assertEqual(values["MAIL_MAX_MESSAGE_MIB"], "300")
                    self.assertEqual(values["MAIL_MAX_ATTACHMENT_MIB"], "200")
                    self.assertEqual(web_path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(request("POST", urlencode(data), headers)[0], 409)
                finally:
                    server.shutdown()
                    thread.join()

    def test_dns_fallback_keeps_tls_identity(self):
        import socket
        import ssl
        context, raw, secured = MagicMock(), MagicMock(), MagicMock()
        context.wrap_socket.return_value = secured
        with patch.object(network, "system_addresses", return_value=["8.8.4.4"]) as local, \
             patch.object(network, "doh_addresses", return_value=["1.1.1.1"]) as doh, \
             patch.object(network.socket, "create_connection", side_effect=[TimeoutError(), raw]) as connect:
            self.assertIs(network.connect_tls("imap.163.com", 993, context), secured)
            self.assertEqual(connect.call_args.args[0], ("1.1.1.1", 993))
            context.wrap_socket.assert_called_once_with(raw, server_hostname="imap.163.com")
            doh.assert_called_once()
            secured.settimeout.assert_called_with(20)
        context.reset_mock()
        with patch.object(network, "system_addresses") as local, \
             patch.object(network, "doh_addresses") as doh, \
             patch.object(network.socket, "create_connection", return_value=raw):
            network.connect_tls("smtp.126.com", 465, context, connect_ip="1.1.1.1")
            local.assert_not_called()
            doh.assert_not_called()
            context.wrap_socket.assert_called_with(raw, server_hostname="smtp.126.com")
        with patch.object(network, "system_addresses", return_value=[]), \
             patch.object(network, "doh_addresses") as doh:
            with self.assertRaises(network.MailConnectionError):
                network.connect_tls("imap.163.com", 993, context, dns_fallback=False)
            doh.assert_not_called()
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError("untrusted")
        with patch.object(network, "system_addresses", return_value=["8.8.4.4"]), \
             patch.object(network, "doh_addresses", return_value=["1.1.1.1"]), \
             patch.object(network.socket, "create_connection", return_value=raw):
            with self.assertRaisesRegex(network.MailConnectionError, "证书"):
                network.connect_tls("imap.163.com", 993, context)
            raw.close.assert_called()
        for address in ("127.0.0.1", "10.0.0.1", "::1", "not-an-ip"):
            with self.assertRaises(ValueError):
                network.public_ip(address)
        with patch.object(network.socket, "getaddrinfo", side_effect=socket.gaierror()):
            self.assertEqual(network.system_addresses("imap.163.com", 993, 1), [])
        stalled = threading.Event()
        with patch.object(network.socket, "getaddrinfo", side_effect=lambda *a, **k: (stalled.wait(1), [])[1]):
            try:
                self.assertEqual(network.system_addresses("imap.163.com", 993, 0.01), [])
            finally:
                stalled.set()
        with patch.object(network, "urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = json.dumps({"Status": 0, "Answer": [
                {"type": 5, "data": "alias.example"}, {"type": 1, "data": "1.1.1.1"}]}).encode()
            self.assertEqual(network.doh_addresses("https://8.8.8.8/resolve", "imap.163.com", "A", 1), ["1.1.1.1"])
            request = urlopen.call_args.args[0]
            self.assertIn("name=imap.163.com", request.full_url)
            for body in (b"not json", b"[]", b'{"Status":2}', b'{"Status":0,"Answer":[{"type":1,"data":"127.0.0.1"}]}'):
                response.read.return_value = body
                self.assertEqual(network.doh_addresses("https://8.8.8.8/resolve", "imap.163.com", "A", 1), [])

    def test_doh_failover_after_dns_failure(self):
        endpoints = ("https://8.8.4.4/resolve", "https://1.0.0.1/dns-query")
        context, raw, secured = MagicMock(), MagicMock(), MagicMock()
        context.wrap_socket.return_value = secured
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"Status": 0, "Answer": [
            None, {"type": 1, "data": "127.0.0.1"}, {"type": 1, "data": "2606:4700:4700::1111"},
            {"type": 1, "data": "8.8.8.8"}, {"type": 1, "data": "8.8.8.8"},
            {"type": 1, "data": "1.1.1.1"},
        ]}).encode()
        with patch.object(network.socket, "getaddrinfo", side_effect=network.socket.gaierror()), \
             patch.object(network, "urlopen", side_effect=[TimeoutError(), response]) as doh, \
             patch.object(network.socket, "create_connection", side_effect=[TimeoutError(), raw]) as connect:
            self.assertIs(network.connect_tls("imap.163.com", 993, context, doh_endpoints=endpoints), secured)
            self.assertEqual([call.args[0] for call in connect.call_args_list], [("8.8.8.8", 993), ("1.1.1.1", 993)])
            self.assertEqual([call.args[0].full_url for call in doh.call_args_list], [
                f"{endpoint}?name=imap.163.com&type=A&edns_client_subnet=0.0.0.0%2F0" for endpoint in endpoints
            ])
            context.wrap_socket.assert_called_once_with(raw, server_hostname="imap.163.com")

    def test_doh_keeps_time_after_local_connection_timeouts(self):
        context, raw = MagicMock(), MagicMock()
        clock = 0

        def connect(address, timeout):
            nonlocal clock
            if address[0] == "1.1.1.1":
                return raw
            clock += timeout
            raise TimeoutError

        with patch.object(network.time, "monotonic", side_effect=lambda: clock), \
             patch.object(network, "system_addresses", return_value=["8.8.8.8", "8.8.4.4", "1.0.0.1", "9.9.9.9"]), \
             patch.object(network, "doh_addresses", return_value=["1.1.1.1"]) as doh, \
             patch.object(network.socket, "create_connection", side_effect=connect):
            self.assertIs(network.connect_tls("smtp.126.com", 465, context, connect_ip="149.112.112.112"),
                          context.wrap_socket.return_value)
            self.assertEqual(clock, 20)
            doh.assert_called_once_with(network.DEFAULT_DOH_ENDPOINTS[0], "smtp.126.com", "A", 5)
            context.wrap_socket.assert_called_once_with(raw, server_hostname="smtp.126.com")

    def test_doh_config_applies_to_setup_and_both_protocols(self):
        endpoints = ("https://1.0.0.1/dns-query", "https://8.8.4.4/resolve")
        values = setup_values("test@163.com", "fake-code")
        self.assertEqual(Mailbox(values).doh_endpoints, network.DEFAULT_DOH_ENDPOINTS)
        for invalid in ("", "http://dns.example", "https://user:pw@dns.example", "https://dns.example?type=A",
                        "https://dns.example#query", "https://dns.example:abc", "https://dns.example,"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "MAIL_DOH_ENDPOINTS"):
                Mailbox({**values, "MAIL_DOH_ENDPOINTS": invalid})
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"MAIL_DNS_FALLBACK": "false", "MAIL_DOH_ENDPOINTS": ", ".join(endpoints)}), \
             patch("netease_email.mail.IMAP4SSL") as imap, patch("netease_email.mail.SMTPSSL") as smtp:
            client = imap.return_value
            client.capability.return_value = ("OK", [b"IMAP4rev1"])
            client.select.return_value = ("OK", [])
            client.response.return_value = ("UIDVALIDITY", [b"42"])
            client.list.return_value = ("OK", [])
            finish_setup(Path(tmp) / "account.env", values)
            for protocol in (imap, smtp):
                self.assertEqual(protocol.call_args.kwargs["doh_endpoints"], endpoints)
                self.assertFalse(protocol.call_args.kwargs["dns_fallback"])

    def test_setup_checks_both_protocols_without_writes(self):
        from test_connector import FakeIMAP, FakeSMTP, ENV
        with patch("netease_email.mail.IMAP4SSL", FakeIMAP), patch("netease_email.mail.SMTPSSL", FakeSMTP):
            result = Mailbox({**ENV, "MAIL_READ_ONLY": "true"}).check_connection()
            self.assertTrue(result["ok"])
            self.assertEqual(result["smtp"], "ok")
            self.assertIn(("SELECT", '"INBOX"', True), FakeIMAP.instances[-1].calls)
            self.assertFalse(hasattr(FakeSMTP.instances[-1], "message"))
        with tempfile.TemporaryDirectory() as tmp, \
             patch("netease_email.cli.Mailbox.check_connection", side_effect=MailError("SMTP: failed")), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("getpass.getpass", return_value="fake-secret"), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            path = Path(tmp) / "failed.env"
            with self.assertRaises(SystemExit):
                main(["--env-file", str(path), "setup", "--email", "fake@163.com", "--enable-writes"])
            self.assertFalse(path.exists())
            self.assertNotIn("fake-secret", err.getvalue())
            self.assertIn("尚未保存", err.getvalue())

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

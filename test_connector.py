"""Offline integration check: python -m unittest -v test_connector (no real mail)."""

import asyncio
import base64
import json
import os
import smtplib
import sys
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mail import (Attachment, AttachmentRef, Compose, Draft, Flags, Mailbox, MailError,
                  MessageRef, Move, Search, decode_folder, encode_folder)
from server import create_services

ENV = {"NETEASE_EMAIL": "test@163.com", "NETEASE_AUTH_CODE": "fake-authorization-code",
       "MAIL_READ_ONLY": "false"}
TOKEN = "test-token-" + "x" * 32
REF = {"folder": "INBOX", "uid": 42, "uidvalidity": 7}
MESSAGE = EmailMessage()
MESSAGE["From"] = "sender@example.com"
MESSAGE["To"] = "test@163.com"
MESSAGE["Subject"] = "中文测试"
MESSAGE["Message-ID"] = "<original@example.com>"
MESSAGE.set_content("邮件正文：你好")
MESSAGE.add_attachment(b"attachment", maintype="text", subtype="plain", filename="附件.txt")
RAW = MESSAGE.as_bytes()


class FakeIMAP:
    instances = []
    advertised = b"IMAP4rev1 ID MOVE"

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.literal = None
        self.instances.append(self)
        assert kwargs["ssl_context"].check_hostname

    def login(self, *args):
        return "OK", [b"logged in"]

    def capability(self):
        return "OK", [self.advertised]

    def _simple_command(self, *args):
        self.calls.append(args)
        return "OK", [b"ID accepted"]

    def select(self, folder, readonly):
        self.calls.append(("SELECT", folder, readonly))
        return "OK", [b"2"]

    def response(self, name):
        if name == "COPYUID":
            return name, [b"7 42 43"]
        return name, [b"7"]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\Trash) "/" "' + encode_folder("已删除 & 归档").encode() + b'"',
                      (b'(\\Drafts) "/" {8}', encode_folder("草稿").encode())]

    def uid(self, *args):
        self.calls.append(args)
        if args[0] == "SEARCH":
            return "OK", [b"40 41 42"]
        if args[0] == "FETCH":
            meta = f"1 (UID {args[1]} FLAGS (\\Flagged) RFC822.SIZE {len(RAW)}".encode()
            return "OK", [(meta, RAW), b")"]
        return "OK", [b"done"]

    def append(self, *args):
        self.calls.append(("APPEND", *args))
        return "OK", [b"saved"]

    def logout(self):
        self.calls.append(("LOGOUT",))


class FakeSMTP:
    refused = {}
    send_error = None
    quit_error = None
    instances = []

    def __init__(self, *args, **kwargs):
        self.instances.append(self)
        assert kwargs["context"].check_hostname

    def login(self, *args):
        pass

    def send_message(self, message, **kwargs):
        self.message, self.envelope = message, kwargs
        if self.send_error:
            raise self.send_error
        return self.refused

    def quit(self):
        if self.quit_error:
            raise self.quit_error


class ConnectorCheck(unittest.TestCase):
    def test_stdio_and_pi_templates(self):
        root = Path(__file__).resolve().parent
        for filename in ("pi-stdio.json", "pi-http.json"):
            definition = json.loads((root / "examples" / filename).read_text())["mcpServers"]["netease_email"]
            self.assertEqual(set(definition["approveTools"]), {"send_email", "save_draft", "set_flags", "move_email"})
            self.assertTrue(definition["directTools"])
        async def check():
            params = StdioServerParameters(command=sys.executable, args=[str(root / "server.py"), "stdio"],
                cwd=str(root.parent), env={**os.environ, **ENV, "CONNECTOR_API_TOKEN": TOKEN, "MAIL_READ_ONLY": "true"})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    self.assertEqual(len(tools), 8)
                    self.assertEqual({t.name for t in tools if t.annotations.destructiveHint}, set(definition["approveTools"]))
                    # Fail closed before a real IMAP/SMTP connection can be opened.
                    result = await session.call_tool("send_email", {"request": {"to": ["nobody@example.com"], "subject": "offline check", "text": "never sent"}})
                    self.assertTrue(result.isError)
                    self.assertIn("disabled", result.content[0].text)
        asyncio.run(check())

    def test_offline_workflow(self):
        with patch.dict(os.environ, ENV, clear=True), patch("mail.imaplib.IMAP4_SSL", FakeIMAP), patch("mail.smtplib.SMTP_SSL", FakeSMTP):
            box = Mailbox()
            for name in ["INBOX", "草稿箱", "已删除 & Archive", '项目 "A"', "📬"]:
                self.assertEqual(decode_folder(encode_folder(name).encode()), name)
            folders = box.list_folders()["folders"]
            self.assertEqual([x["name"] for x in folders], ["INBOX", "已删除 & 归档", "草稿"])

            results = box.search_emails(Search(query='你好" OR ALL', limit=2, unread_only=True, since="2026-01-02"))
            self.assertEqual([m["ref"]["uid"] for m in results["messages"]], [42, 41])
            self.assertEqual(results["next_before_uid"], 41)
            client = FakeIMAP.instances[-1]
            self.assertEqual(client.literal, '你好" OR ALL'.encode())
            search_call = next(c for c in client.calls if c[0] == "SEARCH")
            self.assertEqual(search_call, ("SEARCH", "UTF-8", "UNDELETED", "UNSEEN", "SINCE", "02-Jan-2026", "SUBJECT"))
            self.assertTrue(all("BODY.PEEK" in c[2] for c in client.calls if c[0] == "FETCH"))
            self.assertIn(("SELECT", '"INBOX"', True), client.calls)
            box.search_emails(Search(before_uid=41))
            self.assertIn(("SEARCH", None, "UNDELETED", "UID", "1:40"), FakeIMAP.instances[-1].calls)
            self.assertEqual(box.search_emails(Search(before_uid=1))["messages"], [])

            read = box.read_email(MessageRef(**REF))
            self.assertEqual(read["subject"], "中文测试")
            self.assertIn("你好", read["body"])
            self.assertEqual(read["attachments"][0]["filename"], "附件.txt")
            attachment = box.download_attachment(AttachmentRef(**REF, attachment_id=0))
            self.assertEqual(base64.b64decode(attachment["content_base64"]), b"attachment")
            with self.assertRaises(MailError):
                box.read_email(MessageRef(**{**REF, "uidvalidity": 8}))
            self.assertFalse(any(c[0] == "FETCH" for c in FakeIMAP.instances[-1].calls))

            box.set_flags(Flags(**REF, seen=True, flagged=False))
            self.assertIn(("STORE", "42", "+FLAGS.SILENT", r"(\Seen)"), FakeIMAP.instances[-1].calls)
            self.assertIn(("STORE", "42", "-FLAGS.SILENT", r"(\Flagged)"), FakeIMAP.instances[-1].calls)
            box.move_email(Move(**REF, destination="已删除"))
            self.assertIn(("MOVE", "42", '"' + encode_folder("已删除") + '"'), FakeIMAP.instances[-1].calls)
            with patch.object(FakeIMAP, "advertised", b"IMAP4rev1 ID UIDPLUS"):
                box.move_email(Move(**REF, destination="Trash"))
                self.assertIn(("COPY", "42", '"Trash"'), FakeIMAP.instances[-1].calls)
                self.assertIn(("EXPUNGE", "42"), FakeIMAP.instances[-1].calls)
                with patch.object(FakeIMAP, "response", lambda self, name: (name, [b"7"] if name == "UIDVALIDITY" else [None])):
                    with self.assertRaisesRegex(MailError, "source kept"):
                        box.move_email(Move(**REF, destination="Trash"))
                    self.assertFalse(any(c[0] in {"STORE", "EXPUNGE"} for c in FakeIMAP.instances[-1].calls))
            with patch.object(FakeIMAP, "advertised", b"IMAP4rev1 ID"):
                with self.assertRaises(MailError):
                    box.move_email(Move(**REF, destination="Trash"))
                self.assertFalse(any(c[0] in {"MOVE", "STORE", "COPY", "EXPUNGE"} for c in FakeIMAP.instances[-1].calls))

            compose = Compose(to=["reader@example.com"], bcc=["hidden@example.com"], subject="回复", text="测试",
                              in_reply_to="<original@example.com>",
                              attachments=[Attachment(filename="附件.txt", content_base64="aGk=")])
            sent = box.send_email(compose)
            self.assertEqual(sent["status"], "accepted")
            smtp = FakeSMTP.instances[-1]
            self.assertNotIn("Bcc", smtp.message)
            self.assertIn("hidden@example.com", smtp.envelope["to_addrs"])
            self.assertEqual(smtp.message["In-Reply-To"], "<original@example.com>")
            with patch.object(FakeSMTP, "refused", {"hidden@example.com": (550, b"refused")}):
                sent = box.send_email(compose)
                self.assertEqual(sent["status"], "partially_accepted")
                self.assertEqual(sent["accepted"], ["reader@example.com"])
            with patch.object(FakeSMTP, "quit_error", OSError("lost after accepted")):
                self.assertEqual(box.send_email(compose)["status"], "accepted")
            with patch.object(FakeSMTP, "send_error", OSError("private upstream detail")):
                with self.assertRaisesRegex(MailError, "outcome unknown"):
                    box.send_email(compose)
            with patch.object(FakeSMTP, "send_error", smtplib.SMTPRecipientsRefused({})):
                with self.assertRaisesRegex(MailError, "nothing was sent"):
                    box.send_email(compose)
            box.save_draft(Draft(**compose.model_dump(), folder="草稿"))
            append = next(c for c in FakeIMAP.instances[-1].calls if c[0] == "APPEND")
            self.assertEqual(append[2], r"(\Draft)")
            self.assertIn(b"Bcc: hidden@example.com", append[-1])

            for model, data in [(Search, {"folder": "INBOX\r\nEXPUNGE"}),
                                (Search, {"limit": 31}), (MessageRef, {**REF, "uid": "1:*"}),
                                (Attachment, {"filename": "../secret", "content_base64": "aGk="}),
                                (Attachment, {"filename": "ok", "content_base64": "!bad"}),
                                (Compose, {**compose.model_dump(), "subject": "hello\r\nBcc: bad@example.com"}),
                                (Compose, {**compose.model_dump(), "to": ["a@example.com,b@example.com"]})]:
                with self.assertRaises(ValidationError):
                    model(**data)

            box.read_only = True
            for name, args in [("send_email", compose), ("save_draft", Draft(**compose.model_dump(), folder="Drafts")),
                               ("set_flags", Flags(**REF, seen=True)), ("move_email", Move(**REF, destination="Trash"))]:
                with self.assertRaisesRegex(MailError, "disabled"):
                    getattr(box, name)(args)
            box.read_only = False

            api, mcp = create_services(box, TOKEN)
            with TestClient(api, base_url="http://localhost") as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.post("/api/list_folders").status_code, 401)
                self.assertEqual(client.post("/mcp").status_code, 401)
                self.assertEqual(client.get("/health", headers={"Host": "evil.example"}).status_code, 400)
                schema = client.get("/openapi.json").json()
                self.assertEqual(len(schema["paths"]), 8)
                self.assertTrue(all(len(methods["post"]["description"]) <= 300 for methods in schema["paths"].values()))
                self.assertTrue(schema["paths"]["/api/send_email"]["post"]["x-openai-isConsequential"])
                self.assertFalse(schema["paths"]["/api/read_email"]["post"]["x-openai-isConsequential"])
                client.headers["Authorization"] = f"Bearer {TOKEN}"
                self.assertEqual(client.post("/api/search_emails", json={"query": "中文"}).status_code, 200)
                self.assertEqual(client.post("/api/read_email", json=REF).json()["subject"], "中文测试")
                invalid = client.post("/api/send_email", json={"subject": "PRIVATE-CONTENT"})
                self.assertEqual(invalid.status_code, 422)
                self.assertNotIn("PRIVATE-CONTENT", invalid.text)
                result = client.post("/api/read_email", json={**REF, "uidvalidity": 8})
                self.assertEqual(result.status_code, 502)

                client.headers["Accept"] = "application/json, text/event-stream"
                init = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "offline-check", "version": "1"}}})
                self.assertEqual(init.status_code, 200, init.text)
                client.headers["MCP-Protocol-Version"] = init.json()["result"]["protocolVersion"]
                listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
                self.assertEqual(len(listed["result"]["tools"]), 8)
                result = client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "read_email", "arguments": {"request": REF}}}).json()
                self.assertFalse(result["result"].get("isError"), result)
                self.assertEqual(result["result"]["structuredContent"]["subject"], "中文测试")
                box.read_only = True
                result = client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                    "name": "send_email", "arguments": {"request": compose.model_dump()}}}).json()
                self.assertTrue(result["result"]["isError"])

            # stdio and HTTP share the exact registered tool schemas.
            self.assertEqual(len(asyncio.run(mcp.list_tools())), 8)
            self.assertFalse(any(c in {("EXPUNGE",), ("CLOSE",)} for i in FakeIMAP.instances for c in i.calls))


if __name__ == "__main__":
    unittest.main()

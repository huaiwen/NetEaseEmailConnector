"""Temporary loopback-only configuration form; credentials never enter agent output."""

import html
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

from .cli import SetupError, save_config, setup_values
from .mail import size_limit, MIB


def setup_server(path, address="", writes=False, imap_host="", smtp_host=""):
    route = "/" + secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def reply(self, status, content):
            body = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # no-referrer makes browser form POSTs use Origin: null.
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_target(self):
            return self.path == route and self.headers.get("Host") == self.server.server_name_expected

        def do_GET(self):
            if not self.valid_target():
                self.reply(404, "Not found")
                return
            escape = html.escape
            self.reply(200, f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>连接网易邮箱</title>
<style>body{{font:16px system-ui;max-width:520px;margin:6vh auto;padding:24px;color:#172434;background:#f7f9fc}}
form{{background:white;padding:28px;border:1px solid #dbe2ec;border-radius:16px}}label{{display:block;margin:18px 0 6px}}
input:not([type=checkbox]){{box-sizing:border-box;width:100%;padding:12px;border:1px solid #aeb9c8;border-radius:7px;font:inherit}}
button{{width:100%;padding:13px;margin-top:24px;background:#215cd7;color:white;border:0;border-radius:8px;font:inherit;cursor:pointer}}
p,small{{line-height:1.6;color:#536278}}summary{{cursor:pointer;margin-top:20px}}:focus-visible{{outline:3px solid #95b6ff;outline-offset:2px}}</style>
<h1>连接网易邮箱</h1><p>填写一次，以后直接在对话中使用邮件工具。</p>
<form method="post" action="{route}">
<input type="hidden" name="csrf" value="{route[1:]}">
<label for="email">邮箱地址</label><input id="email" name="email" type="email" maxlength="254" required autocomplete="username" value="{escape(address)}">
<label for="password">客户端授权码</label><input id="password" name="password" type="password" required autocomplete="off" maxlength="4096">
<small>在邮箱设置中开启 IMAP/SMTP，并获取客户端授权码。授权码只保存在本机，不进入对话。</small>
<label><input name="writes" type="checkbox" value="yes" {'checked' if writes else ''}> 允许发送和修改邮件</label>
<p>自动匹配 163、126、yeah.net、VIP 163/126、188 邮箱；学校/企业邮箱使用网易企业邮箱默认服务器。</p>
<details><summary>高级设置（通常无需修改）</summary>
<small>仅在管理员提供了不同服务器时填写。留空自动匹配，TLS 端口为 993 / 465。</small>
<label for="imap">IMAP 主机</label><input id="imap" name="imap_host" value="{escape(imap_host)}" placeholder="自动匹配">
<label for="smtp">SMTP 主机</label><input id="smtp" name="smtp_host" value="{escape(smtp_host)}" placeholder="自动匹配">
<label for="message-mib">整封邮件上限（MiB）</label><input id="message-mib" name="message_mib" type="number" min="1" step="1" value="200" required>
<label for="attachment-mib">单附件上限（MiB）</label><input id="attachment-mib" name="attachment_mib" type="number" min="1" step="1" value="200" required>
<small>整信大小包含附件编码开销，通常比原始文件大约三分之一。邮箱服务商和客户端自身的限制仍适用。</small></details>
<button type="submit">保存配置</button></form><p>此页面只在你的电脑上运行，保存后自动关闭配置服务，10 分钟未操作则过期。</p></html>''')

        def do_POST(self):
            if (not self.valid_target() or self.headers.get("Origin") != self.server.origin
                    or self.headers.get_content_type() != "application/x-www-form-urlencoded"):
                self.reply(403, "Request rejected")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError
                fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True, max_num_fields=8)
                allowed = {"csrf", "email", "password", "writes", "imap_host", "smtp_host", "message_mib", "attachment_mib"}
                if set(fields) - allowed or any(len(v) != 1 for v in fields.values()):
                    raise ValueError
                data = {k: v[0] for k, v in fields.items()}
                if not secrets.compare_digest(data.pop("csrf", "").encode(), route[1:].encode()):
                    raise ValueError
                if data.get("writes", "") not in {"", "yes"}:
                    raise ValueError
                values = setup_values(data.get("email", ""), data.get("password", ""),
                                      data.get("writes") == "yes", data.get("imap_host", ""), data.get("smtp_host", ""))
                for kind in ("MESSAGE", "ATTACHMENT"):
                    values[f"MAIL_MAX_{kind}_MIB"] = str(size_limit(kind, data.get(f"{kind.lower()}_mib", "200")) // MIB)
                save_config(path, values)
            except SetupError as exc:
                self.reply(400, html.escape(str(exc)) + f'<p><a href="{route}">返回重新填写</a></p>')
                return
            except FileExistsError:
                self.reply(409, "配置已存在，未覆盖。请关闭此页面并运行 doctor 检查。")
                return
            except (ValueError, OSError):
                self.reply(400, "无法保存配置。请检查输入和本机文件权限，返回后重试。")
                return
            self.server.configured = True
            self.reply(200, '<meta charset="utf-8"><h1>配置已保存</h1><p>可以关闭此页面，回到对话让助手检查连接。尚未发送或修改邮件。</p>')

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.server_name_expected = f"127.0.0.1:{server.server_port}"
    server.origin = "http://" + server.server_name_expected
    server.setup_url = server.origin + route
    server.configured = False
    server.timeout = 1
    return server


def serve_setup(path, address="", writes=False, imap_host="", smtp_host=""):
    with setup_server(path, address, writes, imap_host, smtp_host) as server:
        print(f"在本机浏览器打开配置页（10 分钟内有效）：{server.setup_url}", flush=True)
        webbrowser.open(server.setup_url)
        deadline = time.monotonic() + 600
        while not server.configured and time.monotonic() < deadline:
            server.handle_request()
        if not server.configured:
            raise SetupError("配置页已过期，尚未保存。请重新运行 setup --web。")
    print(f"Configuration saved: {path}\nRun netease-email-connector doctor to test login (no mail sent).")

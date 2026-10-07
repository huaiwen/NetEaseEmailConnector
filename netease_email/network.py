"""Mail TLS connections with bounded DNS lookup and verified alternate addresses."""

import imaplib
import ipaddress
import json
import queue
import smtplib
import socket
import ssl
import threading
import time
from http.client import HTTPException
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_DNS_SLOTS = threading.BoundedSemaphore(4)


class MailConnectionError(OSError):
    """Credential-free connection diagnostics."""


def public_ip(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or "%" in value:
        raise ValueError("Connect IP must be a public IPv4 or IPv6 address")
    return str(address)


def system_addresses(host, port, timeout):
    # socket timeouts do not bound getaddrinfo. A daemon lets a stuck OS lookup expire.
    if not _DNS_SLOTS.acquire(blocking=False):
        return []
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError:
            result.put([])
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=resolve, daemon=True).start()
    try:
        return list(dict.fromkeys(row[4][0] for row in result.get(timeout=timeout)))[:4]
    except queue.Empty:
        return []


def doh_addresses(endpoint, host, record, timeout):
    query = urlencode({"name": host, "type": record, "edns_client_subnet": "0.0.0.0/0"})
    request = Request(endpoint + "?" + query, headers={"Accept": "application/dns-json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(65537)
        if len(body) > 65536:
            return []
        data = json.loads(body)
        if not isinstance(data, dict) or data.get("Status") != 0:
            return []
        addresses = []
        for answer in data.get("Answer", []):
            if answer.get("type") == (1 if record == "A" else 28):
                address = public_ip(answer["data"])
                if address not in addresses:
                    addresses.append(address)
        return addresses[:4]
    except (OSError, HTTPException, ValueError, TypeError, KeyError, AttributeError):
        return []


def connect_tls(host, port, context, timeout=20, connect_ip="", dns_fallback=True):
    """Retry only before authentication; always keep the original TLS server name."""
    deadline = time.monotonic() + 30
    tried = set()
    certificate_failed = False

    def remaining():
        return max(0, min(5, deadline - time.monotonic()))

    def attempt(addresses):
        nonlocal certificate_failed
        for address in addresses:
            if address in tried or not remaining():
                continue
            tried.add(address)
            raw = None
            try:
                raw = socket.create_connection((address, port), timeout=remaining())
                raw.settimeout(remaining() or 0.001)
                secured = context.wrap_socket(raw, server_hostname=host)
                secured.settimeout(timeout)
                return secured
            except ssl.SSLCertVerificationError:
                certificate_failed = True
            except OSError:
                pass
            finally:
                # wrap_socket takes ownership on success; detached raw.close() is safe.
                if raw is not None:
                    raw.close()
        return None

    if connect_ip:
        secured = attempt([public_ip(connect_ip)])
        if secured is not None:
            return secured
    secured = attempt(system_addresses(host, port, remaining())) if remaining() else None
    if secured is not None:
        return secured
    if dns_fallback:
        # Numeric HTTPS endpoints avoid depending on the failing local DNS resolver.
        for record in ("A", "AAAA"):
            for endpoint in ("https://8.8.8.8/resolve", "https://1.1.1.1/dns-query"):
                if remaining():
                    secured = attempt(doh_addresses(endpoint, host, record, remaining()))
                    if secured is not None:
                        return secured
    detail = "TLS 证书校验失败；请核对官方服务器名。" if certificate_failed else "DNS 解析或 TCP/TLS 连接失败；请检查网络、端口或防火墙。"
    raise MailConnectionError(detail + "可在 https://www.whatsmydns.net/ 查询该主机的 A/AAAA 记录，将公网 IP 填入连接 IP；保留原主机名。")


class IMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, *args, connect_ip="", dns_fallback=True, **kwargs):
        self.connect_ip, self.dns_fallback = connect_ip, dns_fallback
        super().__init__(*args, **kwargs)

    def _create_socket(self, timeout):
        return connect_tls(self.host, self.port, self.ssl_context, timeout,
                           self.connect_ip, self.dns_fallback)


class SMTPSSL(smtplib.SMTP_SSL):
    def __init__(self, *args, connect_ip="", dns_fallback=True, **kwargs):
        self.connect_ip, self.dns_fallback = connect_ip, dns_fallback
        super().__init__(*args, **kwargs)

    def _get_socket(self, host, port, timeout):
        return connect_tls(host, port, self.context, timeout, self.connect_ip, self.dns_fallback)

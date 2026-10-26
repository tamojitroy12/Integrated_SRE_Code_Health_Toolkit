"""Outbound URL validation and SSRF protection (NFR-SEC-09, TH-10)."""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.parse import urlsplit

_resolver_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dns")


class UnsafeUrlError(ValueError):
    pass


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def resolve_host(host: str, port: int, timeout: float = 2.0) -> list[str]:
    future = _resolver_pool.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    try:
        infos = future.result(timeout=timeout)
    except FutureTimeout as exc:
        raise UnsafeUrlError("DNS lookup timed out") from exc
    except OSError as exc:
        raise UnsafeUrlError("host could not be resolved") from exc
    return sorted({str(info[4][0]) for info in infos})


def validate_outbound_url(
    url: str,
    *,
    allow_private: bool = False,
    require_https: bool = True,
    resolve: bool = True,
) -> str:
    """Validate a user-supplied URL before any request is made to it.

    Rejects non-HTTP(S) schemes, embedded credentials, and hosts that resolve to private,
    loopback, link-local or otherwise non-public addresses (unless ``allow_private``).
    """
    if len(url) > 2048:
        raise UnsafeUrlError("URL too long")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http"):
        raise UnsafeUrlError("URL scheme must be https")
    if require_https and scheme != "https" and not allow_private:
        raise UnsafeUrlError("URL scheme must be https")
    if parts.username or parts.password or "@" in parts.netloc:
        raise UnsafeUrlError("URL must not contain credentials")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL must include a host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("invalid port") from exc
    if allow_private:
        return url
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_ip(literal):
            raise UnsafeUrlError("URL host is a private or loopback address")
        return url
    if host.lower() in ("localhost",) or host.lower().endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrlError("URL host is not public")
    if resolve:
        for addr in resolve_host(host, port):
            if not is_public_ip(ipaddress.ip_address(addr.split("%")[0])):
                raise UnsafeUrlError("URL host resolves to a private or loopback address")
    return url


def mask_url_host(url: str) -> dict[str, str | int]:
    """Projection used when showing a stored secret URL: host (and non-default port)."""
    parts = urlsplit(url)
    out: dict[str, str | int] = {"host": parts.hostname or ""}
    try:
        port = parts.port
    except ValueError:
        port = None
    default = 443 if parts.scheme == "https" else 80
    if port and port != default:
        out["port"] = port
    return out

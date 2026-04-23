"""SSRF guard for outbound HTTP requests against user-supplied URLs.

Used before any ``requests.get(user_url, ...)``. The guard:

1. Accepts only ``http`` / ``https`` schemes.
2. Resolves the hostname to all A/AAAA addresses.
3. Rejects if any resolved address is private, loopback, link-local,
   reserved, multicast, or unspecified -- including the cloud metadata IP
   ``169.254.169.254`` (which is link-local).
4. Checks every address, not just the first. A hostname that resolves to
   one public and one private IP is rejected; this blocks DNS rebinding
   where an attacker controls a domain that flips between the two.

Caller is expected to use the *original* URL, not a resolved IP, so the
TLS hostname check still works downstream.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a user-supplied URL fails SSRF checks."""


_ALLOWED_SCHEMES = ('http', 'https')


def assert_safe_url(url: str) -> None:
    """Raise UnsafeURLError if ``url`` is not safe to fetch."""
    if not url or not isinstance(url, str):
        raise UnsafeURLError('URL is empty')

    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f'URL scheme {parsed.scheme!r} not allowed; use http or https'
        )

    host = parsed.hostname
    if not host:
        raise UnsafeURLError('URL has no hostname')

    # Reject literal IPs that are private without bothering DNS. urlparse
    # already strips brackets from IPv6 hosts.
    try:
        literal = ipaddress.ip_address(host)
        _check_ip(literal, host)
        # Literal public IP: still allow, but no resolution needed.
        return
    except ValueError:
        pass  # not a literal IP; continue to DNS resolution

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f'Could not resolve {host!r}: {e}') from e

    seen = set()
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise UnsafeURLError(f'Resolved address {ip_str!r} is not a valid IP')
        _check_ip(ip, host)


def _check_ip(ip: ipaddress._BaseAddress, host: str) -> None:
    # ``is_global`` is True only for addresses in public ranges; it is False
    # for private, loopback, link-local, multicast, reserved, unspecified.
    # That single check covers 169.254.169.254 (link-local), 127.0.0.0/8,
    # 10/8, 172.16/12, 192.168/16, ::1, fe80::/10, fc00::/7, and friends.
    if not ip.is_global:
        raise UnsafeURLError(
            f'URL host {host!r} resolves to non-public address {ip}'
        )

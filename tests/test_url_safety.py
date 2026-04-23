"""Unit tests for the SSRF guard."""

from unittest.mock import patch

import pytest

from app.services.url_safety import assert_safe_url, UnsafeURLError


def _fake_resolve(*ip_strs):
    """Patch socket.getaddrinfo to return the given IP strings."""
    return patch(
        'app.services.url_safety.socket.getaddrinfo',
        return_value=[(0, 0, 0, '', (ip, 0)) for ip in ip_strs],
    )


class TestSchemes:
    def test_https_allowed(self):
        with _fake_resolve('93.184.216.34'):
            assert_safe_url('https://example.com/path')

    def test_http_allowed(self):
        with _fake_resolve('93.184.216.34'):
            assert_safe_url('http://example.com')

    def test_file_rejected(self):
        with pytest.raises(UnsafeURLError, match='scheme'):
            assert_safe_url('file:///etc/passwd')

    def test_ftp_rejected(self):
        with pytest.raises(UnsafeURLError, match='scheme'):
            assert_safe_url('ftp://example.com')

    def test_javascript_rejected(self):
        with pytest.raises(UnsafeURLError, match='scheme'):
            assert_safe_url('javascript:alert(1)')

    def test_empty_rejected(self):
        with pytest.raises(UnsafeURLError):
            assert_safe_url('')


class TestPrivateLiterals:
    def test_loopback_v4(self):
        with pytest.raises(UnsafeURLError, match='non-public'):
            assert_safe_url('http://127.0.0.1/')

    def test_loopback_v6(self):
        with pytest.raises(UnsafeURLError, match='non-public'):
            assert_safe_url('http://[::1]/')

    def test_rfc1918_10(self):
        with pytest.raises(UnsafeURLError, match='non-public'):
            assert_safe_url('http://10.0.0.1/')

    def test_rfc1918_172(self):
        with pytest.raises(UnsafeURLError, match='non-public'):
            assert_safe_url('http://172.16.5.1/')

    def test_rfc1918_192(self):
        with pytest.raises(UnsafeURLError, match='non-public'):
            assert_safe_url('http://192.168.1.1/')

    def test_aws_metadata_ip(self):
        # 169.254.169.254 is link-local (not "is_global"), so this hits the
        # same code path as other link-local addresses.
        with pytest.raises(UnsafeURLError, match='non-public'):
            assert_safe_url('http://169.254.169.254/latest/meta-data/')


class TestDNSResolution:
    def test_public_ip_allowed(self):
        with _fake_resolve('8.8.8.8'):
            assert_safe_url('https://dns.google/resolve')

    def test_resolves_to_private_rejected(self):
        with _fake_resolve('10.0.0.5'):
            with pytest.raises(UnsafeURLError, match='non-public'):
                assert_safe_url('https://intranet.example.com/')

    def test_dns_rebinding_mixed_addresses_rejected(self):
        # Hostname returns one public + one private address. Must reject:
        # otherwise an attacker can race the resolver between the SSRF check
        # and the actual fetch.
        with _fake_resolve('8.8.8.8', '127.0.0.1'):
            with pytest.raises(UnsafeURLError, match='non-public'):
                assert_safe_url('https://attacker.example.com/')

    def test_resolution_failure_rejected(self):
        import socket
        with patch(
            'app.services.url_safety.socket.getaddrinfo',
            side_effect=socket.gaierror('no such host'),
        ):
            with pytest.raises(UnsafeURLError, match='resolve'):
                assert_safe_url('https://nonexistent.invalid/')

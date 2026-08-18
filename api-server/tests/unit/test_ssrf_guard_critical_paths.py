from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from services.ssrf_guard import SSRFBlocked, assert_safe_external_url


def test_ssrf_rejects_non_http_schemes_and_missing_hostname():
    with pytest.raises(SSRFBlocked, match="Schéma"):
        assert_safe_external_url("file:///etc/passwd")
    with pytest.raises(SSRFBlocked, match="hostname"):
        assert_safe_external_url("https://")


def test_ssrf_rejects_explicit_blocked_hostnames():
    with pytest.raises(SSRFBlocked, match="Hostname interdit"):
        assert_safe_external_url("http://localhost/health")
    with pytest.raises(SSRFBlocked, match="Hostname interdit"):
        assert_safe_external_url("https://metadata.google.internal/")


def test_ssrf_rejects_unresolvable_hostnames():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("not found")):
        with pytest.raises(SSRFBlocked, match="Résolution DNS impossible"):
            assert_safe_external_url("https://external.example.invalid")


def test_ssrf_rejects_private_loopback_link_local_reserved_and_multicast_ips():
    blocked = ["10.0.0.4", "127.0.0.1", "169.254.169.254", "224.0.0.1"]
    for address in blocked:
        with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, 0, 0, "", (address, 443))]):
            with pytest.raises(SSRFBlocked, match="IP interne/réservée"):
                assert_safe_external_url("https://external.example")


def test_ssrf_allows_public_ip_resolution():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, 0, 0, "", ("93.184.216.34", 443))]):
        assert_safe_external_url("https://example.com/api") is None

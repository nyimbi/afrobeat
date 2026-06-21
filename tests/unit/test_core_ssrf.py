from __future__ import annotations

"""Unit tests for gbedu_core.ssrf — SSRF URL validation."""

import socket
from unittest.mock import patch

import pytest

from gbedu_core.ssrf import validate_no_ssrf, _check_host_directly, _assert_not_blocked
import ipaddress


# ── validate_no_ssrf ──────────────────────────────────────────────────────────

def test_public_url_passes() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 443))]):
		validate_no_ssrf("https://api.example.com/v1/resource")  # should not raise


def test_ftp_scheme_rejected() -> None:
	with pytest.raises(ValueError, match="scheme"):
		validate_no_ssrf("ftp://example.com/file.txt")


def test_file_scheme_rejected() -> None:
	with pytest.raises(ValueError, match="scheme"):
		validate_no_ssrf("file:///etc/passwd")


def test_no_hostname_rejected() -> None:
	with pytest.raises(ValueError, match="hostname"):
		validate_no_ssrf("https://")


def test_localhost_rejected() -> None:
	with pytest.raises(ValueError, match="blocked"):
		validate_no_ssrf("http://localhost/admin")


def test_ip6_localhost_rejected() -> None:
	with pytest.raises(ValueError, match="blocked"):
		validate_no_ssrf("http://ip6-localhost/admin")


def test_loopback_ip_rejected() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))]):
		with pytest.raises(ValueError, match="blocked"):
			validate_no_ssrf("http://127.0.0.1/admin")


def test_rfc1918_10_rejected() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("10.0.0.1", 80))]):
		with pytest.raises(ValueError, match="blocked"):
			validate_no_ssrf("http://internal.corp/secret")


def test_rfc1918_192168_rejected() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("192.168.1.100", 80))]):
		with pytest.raises(ValueError, match="blocked"):
			validate_no_ssrf("http://router.local/")


def test_rfc1918_172_rejected() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("172.16.0.5", 80))]):
		with pytest.raises(ValueError, match="blocked"):
			validate_no_ssrf("http://docker.internal/")


def test_aws_metadata_rejected() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("169.254.169.254", 80))]):
		with pytest.raises(ValueError, match="blocked"):
			validate_no_ssrf("http://metadata.link/iam/token")


def test_cgnat_rejected() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("100.64.0.1", 80))]):
		with pytest.raises(ValueError, match="blocked"):
			validate_no_ssrf("http://cgnat.example/")


def test_ipv6_loopback_rejected() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("::1", 80))]):
		with pytest.raises(ValueError, match="blocked"):
			validate_no_ssrf("http://[::1]/")


def test_dns_failure_raises_value_error() -> None:
	with patch("socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
		with pytest.raises(ValueError, match="resolve"):
			validate_no_ssrf("http://nonexistent.invalid/path")


def test_direct_ip_loopback_rejected() -> None:
	with pytest.raises(ValueError, match="blocked"):
		validate_no_ssrf("http://127.0.0.1/")


def test_direct_private_ip_rejected() -> None:
	with pytest.raises(ValueError, match="blocked"):
		validate_no_ssrf("http://10.10.10.10/")


def test_http_scheme_allowed() -> None:
	with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 80))]):
		validate_no_ssrf("http://example.com/page")


# ── _check_host_directly ──────────────────────────────────────────────────────

def test_check_host_localhost_raises() -> None:
	with pytest.raises(ValueError, match="loopback"):
		_check_host_directly("localhost")


def test_check_host_ip6_localhost_raises() -> None:
	with pytest.raises(ValueError, match="loopback"):
		_check_host_directly("ip6-localhost")


def test_check_host_ip6_loopback_raises() -> None:
	with pytest.raises(ValueError, match="loopback"):
		_check_host_directly("ip6-loopback")


def test_check_host_raw_private_ip_raises() -> None:
	with pytest.raises(ValueError, match="blocked"):
		_check_host_directly("192.168.0.1")


def test_check_host_public_ip_passes() -> None:
	_check_host_directly("8.8.8.8")  # should not raise


def test_check_host_domain_passes() -> None:
	_check_host_directly("api.openai.com")  # not an IP, DNS handles it


# ── _assert_not_blocked ───────────────────────────────────────────────────────

def test_assert_not_blocked_public_passes() -> None:
	ip = ipaddress.ip_address("8.8.8.8")
	_assert_not_blocked(ip, "https://dns.google/")  # should not raise


def test_assert_not_blocked_private_raises() -> None:
	ip = ipaddress.ip_address("10.0.0.1")
	with pytest.raises(ValueError, match="blocked"):
		_assert_not_blocked(ip, "http://internal/")


def test_assert_not_blocked_ipv4_vs_ipv6_no_crash() -> None:
	# IPv6 address checked against IPv4 network — TypeError is silently swallowed
	ip = ipaddress.ip_address("::1")
	# May or may not raise depending on which network matches first; must not crash
	try:
		_assert_not_blocked(ip, "http://[::1]/")
	except ValueError:
		pass  # expected if IPv6 loopback network matches

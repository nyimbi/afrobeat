"""SSRF URL validation (FMEA S03).

Reject any user-supplied URL that resolves to a private, link-local, or loopback
address before the server makes an outbound HTTP request. Prevents attackers from
probing internal metadata services (169.254.169.254/AWS, 10.0.0.1/cluster).

Usage:
    from gbedu_core.ssrf import validate_no_ssrf
    validate_no_ssrf(user_supplied_url)   # raises ValueError on blocked URLs
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


# Private / reserved ranges that must never be reachable via user-supplied URLs.
_BLOCKED_NETWORKS = [
	ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918
	ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918
	ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918
	ipaddress.ip_network("127.0.0.0/8"),       # loopback
	ipaddress.ip_network("169.254.0.0/16"),    # link-local / AWS metadata
	ipaddress.ip_network("::1/128"),           # IPv6 loopback
	ipaddress.ip_network("fc00::/7"),          # IPv6 unique-local
	ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
	ipaddress.ip_network("100.64.0.0/10"),     # CGNAT (RFC 6598)
	ipaddress.ip_network("0.0.0.0/8"),         # unspecified
]


def validate_no_ssrf(url: str) -> None:
	"""Raise ValueError if `url` points to a blocked (private/internal) address.

	Call before making any outbound HTTP request to a user-supplied URL.
	Does NOT make a network request; resolves the hostname to an IP and validates
	the IP against the blocked network list.
	"""
	parsed = urlparse(url)

	if parsed.scheme not in ("http", "https"):
		raise ValueError(
			f"URL scheme {parsed.scheme!r} is not allowed — only http and https are permitted"
		)

	host = parsed.hostname
	if not host:
		raise ValueError("URL has no hostname")

	# Reject numeric IPs and 'localhost' variants before DNS resolution.
	_check_host_directly(host)

	# DNS resolution — any A/AAAA record that lands in a blocked range is rejected.
	try:
		infos = socket.getaddrinfo(host, None)
	except socket.gaierror as exc:
		raise ValueError(f"Could not resolve hostname {host!r}: {exc}") from exc

	for _family, _type, _proto, _canon, sockaddr in infos:
		ip_str = sockaddr[0]
		try:
			ip = ipaddress.ip_address(ip_str)
		except ValueError:
			continue
		_assert_not_blocked(ip, url)


def _check_host_directly(host: str) -> None:
	"""Reject hostnames that are obviously private without DNS resolution."""
	if host in ("localhost", "ip6-localhost", "ip6-loopback"):
		raise ValueError(f"Host {host!r} is blocked (loopback alias)")

	try:
		ip = ipaddress.ip_address(host)
	except ValueError:
		return  # not a raw IP — DNS resolution will handle it
	_assert_not_blocked(ip, host)


def _assert_not_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, url: str) -> None:
	for net in _BLOCKED_NETWORKS:
		try:
			if ip in net:
				raise ValueError(
					f"URL {url!r} resolves to a blocked address {ip} "
					f"(matches {net}) — SSRF protection"
				)
		except TypeError:
			pass  # IPv4/IPv6 mismatch — skip

"""
Outbound-URL guard against SSRF (Fase 11.4).

check_service_status makes the Aether server itself issue an HTTP request.
Without this guard, anyone who can influence the URL (an LLM, an employee
in the chat, a tenant admin's config) can make our server probe its own
network: cloud metadata (169.254.169.254), localhost admin ports, other
tenants' internal hosts.

Rules: http/https only, no credentials in the URL, and every address the
host resolves to must be publicly routable — unless the deployment opts in
with ALLOW_PRIVATE_HEALTHCHECK_TARGETS (self-hosted Aether monitoring an
intranet). Link-local/metadata addresses are refused even then.

Known limit: DNS is resolved here and again by the HTTP client, so a
hostile DNS server could answer differently the second time (rebinding).
Redirects are not followed (see mcp_server.check_service_status), which
closes the easier variant of the same attack.
"""
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    """The URL must not be requested by the server."""


_ALLOWED_SCHEMES = {"http", "https"}


def _is_allowed_ip(ip: ipaddress._BaseAddress, allow_private: bool) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False  # metadata endpoints live here; never a legit healthcheck
    if ip.is_global:
        return True
    return allow_private and (ip.is_private or ip.is_loopback)


def resolve_host(host: str) -> list[str]:
    """All addresses `host` resolves to (separate function so tests can stub DNS)."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def validate_outbound_url(url: str, *, allow_private: bool = False) -> str:
    """Returns the URL unchanged if it is safe to request, else raises UnsafeURLError."""
    try:
        parts = urlsplit(url.strip())
    except ValueError as e:
        raise UnsafeURLError("malformed URL") from e
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError("only http/https URLs are allowed")
    if not parts.hostname:
        raise UnsafeURLError("URL has no host")
    if parts.username or parts.password:
        raise UnsafeURLError("credentials in URLs are not allowed")

    try:
        literal = ipaddress.ip_address(parts.hostname)
        addresses = [str(literal)]
    except ValueError:
        try:
            addresses = resolve_host(parts.hostname)
        except OSError as e:
            raise UnsafeURLError("host does not resolve") from e

    for address in addresses:
        if not _is_allowed_ip(ipaddress.ip_address(address.split("%")[0]), allow_private):
            raise UnsafeURLError("host resolves to a non-public address")
    return url

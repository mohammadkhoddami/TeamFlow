"""SSRF guard for user/admin-supplied outbound URLs.

Two levels:
  validate_outbound_url()   - cheap, no DNS; called when a URL is saved.
  assert_deliverable_url()  - resolves the host and requires every address to
                              be globally routable; called immediately before
                              an outbound request.

Private, loopback, link-local (including cloud metadata), reserved and
multicast ranges are rejected. Delivery re-resolves the host, which also
contains DNS-rebinding windows. ``OUTBOUND_ALLOW_PRIVATE_HOSTS`` exists for
local development (e.g. docker-compose webhook receivers) and must stay false
in production.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import settings
from app.core.exceptions import ValidationFailedError

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal")


def _check_host(host: str, *, resolve: bool) -> None:
    if not host:
        raise ValidationFailedError("URL must include a host")
    lowered = host.lower().rstrip(".")
    if lowered in _BLOCKED_HOSTNAMES or lowered.endswith(_BLOCKED_SUFFIXES):
        raise ValidationFailedError("URL must point to a public host")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise ValidationFailedError("URL must point to a public IP address")
        return

    if not resolve:
        return

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValidationFailedError("URL host cannot be resolved") from None
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise ValidationFailedError("URL host cannot be resolved")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValidationFailedError("URL must point to a public IP address")


def _parse(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValidationFailedError("URL must use http or https")
    return parsed.hostname or ""


def validate_outbound_url(url: str) -> str:
    """Save-time check: scheme plus literal-IP/hostname denylists. No DNS, so
    offline environments can still store URLs that resolve later."""
    host = _parse(url)
    if settings.outbound_allow_private_hosts:
        return url
    _check_host(host, resolve=False)
    return url


def assert_deliverable_url(url: str) -> str:
    """Delivery-time check: DNS is mandatory and every resolved address must
    be globally routable. Failure is permanent (do not retry)."""
    host = _parse(url)
    if settings.outbound_allow_private_hosts:
        return url
    _check_host(host, resolve=True)
    return url

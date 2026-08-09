"""SSRF defenses for user-configurable literature provider endpoints."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit


class ProviderBaseUrlError(ValueError):
    """Raised when a provider endpoint is unsafe or cannot be verified."""


AddressResolver = Callable[[str, int], Iterable[str]]


def resolve_host_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve every stream address for a hostname without making an HTTP request."""
    records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(record[4][0] for record in records))


def _address_is_forbidden(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise ProviderBaseUrlError("provider hostname resolved to an invalid address") from error
    return (
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def validate_provider_base_url(
    value: str,
    *,
    resolver: AddressResolver = resolve_host_addresses,
) -> str:
    """Require a public HTTPS endpoint and reject unsafe DNS resolutions.

    This validation is intentionally called both when an API profile is saved and
    immediately before the registry builds a provider for a request. Redirects are
    disabled in each provider client so a validated public endpoint cannot redirect
    the client to a private target.
    """
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https":
        raise ProviderBaseUrlError("provider base URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderBaseUrlError("provider base URL must not contain credentials")
    if parsed.fragment:
        raise ProviderBaseUrlError("provider base URL must not contain a fragment")

    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if not hostname:
        raise ProviderBaseUrlError("provider base URL must include a hostname")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ProviderBaseUrlError("local provider hosts are not allowed")
    if "%" in hostname:
        raise ProviderBaseUrlError("scoped IP addresses are not allowed")

    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None

    if literal_address is not None:
        addresses = (str(literal_address),)
    else:
        try:
            addresses = tuple(resolver(hostname, parsed.port or 443))
        except (OSError, ValueError) as error:
            raise ProviderBaseUrlError("provider hostname could not be safely resolved") from error
        if not addresses:
            raise ProviderBaseUrlError("provider hostname did not resolve to an address")

    if any(_address_is_forbidden(address) for address in addresses):
        raise ProviderBaseUrlError("provider hostname resolves to a non-public address")
    return value

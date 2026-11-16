"""Prefer IPv4 resolver results when a host offers both A and AAAA records.

Some VPN/TUN setups terminate IPv6 TLS for LLM API endpoints while IPv4 stays
reachable. Async HTTP clients (httpcore's anyio happy-eyeballs path) prefer
IPv6 and then fail mid-handshake, while sync clients try addresses in resolver
order and usually reach IPv4. Filtering AAAA results at the resolver level
makes both paths behave the same. Hosts that only publish AAAA records keep
working unchanged.
"""

from __future__ import annotations

import os
import socket
from typing import Any

_PATCH_MARKER = "_mobilerun_ipv4_preference_original"

_DISABLE_VALUES = {"1", "true", "yes"}


def _disabled_by_env() -> bool:
    return os.environ.get("MOBILERUN_DISABLE_IPV4_PREFERENCE", "").strip().lower() in (
        _DISABLE_VALUES
    )


def prefer_ipv4_when_supported() -> None:
    """Wrap ``socket.getaddrinfo`` once to drop AAAA results when A records exist.

    Idempotent: repeated calls keep the first wrapper. Set
    ``MOBILERUN_DISABLE_IPV4_PREFERENCE=1`` to skip patching, for example on a
    network where IPv6 is the only working route to the model API.
    """
    if _disabled_by_env():
        return
    current = socket.getaddrinfo
    if getattr(current, _PATCH_MARKER, None) is not None:
        return

    def getaddrinfo_with_ipv4_preference(*args: Any, **kwargs: Any):
        results = current(*args, **kwargs)
        ipv4 = [entry for entry in results if entry[0] == socket.AF_INET]
        return ipv4 if ipv4 else results

    getaddrinfo_with_ipv4_preference._mobilerun_ipv4_preference_original = current
    socket.getaddrinfo = getaddrinfo_with_ipv4_preference

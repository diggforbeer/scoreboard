"""The board's own address on the network (#293)."""

from __future__ import annotations

import socket

#: TEST-NET-1 (RFC 5737): never routed, so nothing real is contacted. Only
#: used to ask the kernel which local address it would send from.
_PROBE_ADDRESS = "192.0.2.1"


def default_route_ip() -> str | None:
    """The IPv4 address on the default route, or ``None`` with no route.

    A board on both Ethernet and Wi-Fi has two addresses; the one the kernel
    would use to reach the internet is the one the owner's phone can also
    reach. Connecting a UDP socket sends no packet -- it only selects a
    route -- and fails with ``OSError`` when there is no default route,
    which is exactly the "offline" answer the caller wants.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((_PROBE_ADDRESS, 9))
            ip = sock.getsockname()[0]
    except OSError:
        return None
    return ip if ip not in ("", "0.0.0.0") else None

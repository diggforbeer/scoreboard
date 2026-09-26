"""Best-effort local IP lookup, for the boot splash's headless troubleshooting.

Not a general networking module -- this exists for exactly one caller:
the "connecting" scene, which wants to show the board's LAN address once
DHCP has handed one out, and fall back to a plain "CONNECTING" message
before that.
"""

from __future__ import annotations

import socket

#: Never actually contacted: UDP "connect" only resolves the local route
#: that would be used to reach it, so this works offline too (it raises
#: immediately when there is no default route yet, which is exactly the
#: "no IP" signal the splash wants -- no timeout to wait out).
_PROBE_ADDRESS = ("1.1.1.1", 80)


def local_ip() -> str | None:
    """The LAN IP the board would be reached at, or None before DHCP completes."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(_PROBE_ADDRESS)
            return sock.getsockname()[0]
        except OSError:
            return None

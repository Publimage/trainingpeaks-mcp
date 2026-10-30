"""Bounded, read-only runtime listener inventory for the existing TP host.

No subprocesses, repository operations, network connections or provider calls.
This reports socket observations, not application health or firewall policy.
"""
from __future__ import annotations

import socket
from pathlib import Path

_PROC_TCP = Path("/proc/net/tcp")
_BRIDGE_PORT = 8787
_TUNNEL_PORT = 8080


def _listening_ipv4(path: Path = _PROC_TCP) -> set[tuple[str, int]] | None:
    """Read Linux kernel TCP state; return None when it cannot be inspected."""
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    result: set[tuple[str, int]] = set()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[3] != "0A":  # TCP_LISTEN
            continue
        try:
            address_hex, port_hex = parts[1].split(":")
            if len(address_hex) != 8 or len(port_hex) != 4:
                continue
            address = socket.inet_ntoa(bytes.fromhex(address_hex)[::-1])
            port = int(port_hex, 16)
        except (ValueError, OSError):
            continue
        result.add((address, port))
    return result


def tp_get_ironman_runtime_status() -> dict[str, str | int]:
    """Describe only the known TP private bridge and localhost tunnel listeners."""
    listeners = _listening_ipv4()
    if listeners is None:
        bridge = tunnel = "UNKNOWN"
    else:
        bridge = ("LISTENING" if any(ip.startswith("10.") and port == _BRIDGE_PORT
                                     for ip, port in listeners) else "NOT_OBSERVED")
        tunnel = ("LISTENING" if ("127.0.0.1", _TUNNEL_PORT) in listeners
                  else "NOT_OBSERVED")
    return {
        "schema": "IRONMAN_RUNTIME_LISTENERS_V1",
        "bridge_listener": bridge,
        "tunnel_listener": tunnel,
        "evidence": "linux_proc_tcp_local_namespace",
        "provider_writes": 0,
    }

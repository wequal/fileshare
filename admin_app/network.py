"""Network helpers for displaying the LAN URL."""

from __future__ import annotations

import ipaddress
import socket
from typing import List, Optional


def primary_lan_ip() -> Optional[str]:
    """Return the IP the OS would use for outbound traffic (no packet sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Address need not be reachable; this just tells the OS to choose
        # the default route's source IP.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = None
    finally:
        s.close()
    return ip


def all_ipv4_addresses() -> List[str]:
    """Return all non-loopback IPv4 addresses for this host."""
    ips: List[str] = []
    seen: set = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip in seen:
                continue
            seen.add(ip)
            try:
                addr = ipaddress.IPv4Address(ip)
            except ipaddress.AddressValueError:
                continue
            if addr.is_loopback:
                continue
            ips.append(ip)
    except socket.gaierror:
        pass

    primary = primary_lan_ip()
    if primary and primary not in seen:
        ips.insert(0, primary)
    elif primary and primary in ips:
        ips.remove(primary)
        ips.insert(0, primary)

    return ips


def server_url(port: int, ip: Optional[str] = None) -> str:
    host = ip or primary_lan_ip() or "127.0.0.1"
    return f"http://{host}:{port}"

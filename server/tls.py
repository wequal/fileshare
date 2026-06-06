"""Self-signed TLS certificate handling for the LAN file server.

HTTPS is what unlocks iOS "Save to Photos" (the Web Share API needs a secure
context). On a LAN there's no public CA, so we generate a self-signed
certificate that satisfies Apple's modern requirements:

* RSA 2048-bit key, SHA-256 signature
* Subject Alternative Names (iOS ignores the legacy CN)
* validity <= 825 days (iOS 13+ rejects longer-lived certs)
* extendedKeyUsage = serverAuth

The cert doubles as its own root so it can be installed and trusted on the
iPhone (Settings -> General -> VPN & Device Management, then enable full trust
under Certificate Trust Settings).
"""

from __future__ import annotations

import datetime
import ipaddress
import socket
from pathlib import Path
from typing import List, Optional, Tuple

from server.config import Settings, get_settings

# iOS requires server certs to be valid for 825 days or fewer.
_MAX_VALID_DAYS = 800


def _local_ipv4_addresses() -> List[str]:
    """Best-effort list of this machine's IPv4 addresses for the cert SAN."""
    ips: set[str] = {"127.0.0.1"}

    # Primary LAN address (no traffic actually sent; just selects the route).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass

    # Everything resolvable for the hostname.
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass

    return sorted(ips)


def _hostnames() -> List[str]:
    names = {"localhost"}
    try:
        names.add(socket.gethostname())
    except OSError:
        pass
    return sorted(names)


def generate_self_signed(
    cert_path: Path,
    key_path: Path,
    extra_hosts: Optional[List[str]] = None,
) -> Tuple[Path, Path]:
    """Write a fresh self-signed cert/key pair covering this machine's IPs."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    san: List[x509.GeneralName] = []
    for host in _hostnames() + list(extra_hosts or []):
        san.append(x509.DNSName(host))
    for ip in _local_ipv4_addresses():
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            san.append(x509.DNSName(ip))

    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Home Fileshare")]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=_MAX_VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    # Best effort: keep the private key readable only by the owner.
    try:
        import os

        os.chmod(key_path, 0o600)
    except OSError:
        pass

    return cert_path, key_path


def ensure_server_cert(
    settings: Optional[Settings] = None,
) -> Optional[Tuple[str, str]]:
    """Return (cert_file, key_file) when HTTPS is enabled, generating if needed.

    Returns ``None`` when ``use_https`` is disabled so callers can fall back to
    plain HTTP.
    """
    s = settings or get_settings()
    if not s.use_https:
        return None

    cert_path = s.tls_cert_path
    key_path = s.tls_key_path
    if not cert_path.is_file() or not key_path.is_file():
        generate_self_signed(cert_path, key_path)
    return str(cert_path), str(key_path)

"""Generate a self-signed TLS certificate for serving the app over HTTPS.

HTTPS is required for the iPhone "Save to Photos" feature (the Web Share API
needs a secure context). Run this once per machine; the certificate embeds the
machine's current LAN IP addresses.

Usage (from the project root, inside the venv):

    python scripts/generate_cert.py            # create if missing
    python scripts/generate_cert.py --force    # overwrite existing
    python scripts/generate_cert.py --host fileshare.local  # extra SAN entry
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import get_settings  # noqa: E402
from server.tls import generate_self_signed  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a self-signed TLS cert.")
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing certificate."
    )
    parser.add_argument(
        "--host",
        action="append",
        default=[],
        help="Extra hostname/IP to include in the certificate (repeatable).",
    )
    args = parser.parse_args()

    settings = get_settings()
    cert_path = settings.tls_cert_path
    key_path = settings.tls_key_path

    if cert_path.is_file() and key_path.is_file() and not args.force:
        print(f"Certificate already exists: {cert_path}")
        print("Use --force to regenerate.")
        return

    generate_self_signed(cert_path, key_path, extra_hosts=args.host)
    print(f"Wrote certificate: {cert_path}")
    print(f"Wrote private key: {key_path}")
    print("\nSet 'use_https: true' in config.yaml, then restart the server.")
    print("On the iPhone, open the HTTPS URL and trust the certificate when prompted.")


if __name__ == "__main__":
    main()

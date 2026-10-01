#!/usr/bin/env python3
"""Generate Jarvis HUD self-signed TLS cert with LAN IP SANs (Windows-friendly)."""
from __future__ import annotations

import ipaddress
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parent.parent
CERTS = ROOT / "certs"
HUD_CER = ROOT / "hud" / "jarvis.cer"


def detect_lan_ips() -> list[str]:
    ips = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    # Also try UDP connect trick for primary outbound IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    for arg in sys.argv[1:]:
        ips.add(arg)
    return sorted(ips)


def main() -> None:
    CERTS.mkdir(parents=True, exist_ok=True)
    lan_ips = detect_lan_ips()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jarvis HUD")])
    san = [
        x509.DNSName("jarvis.local"),
        x509.DNSName("jarvis"),
        x509.DNSName("localhost"),
    ]
    for ip in lan_ips:
        san.append(x509.IPAddress(ipaddress.ip_address(ip)))

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    (CERTS / "key.pem").write_bytes(key_pem)
    (CERTS / "cert.pem").write_bytes(cert_pem)
    HUD_CER.write_bytes(cert_pem)
    print(f"Wrote {CERTS / 'cert.pem'} with SANs for: {', '.join(lan_ips)}")
    print(f"Also wrote {HUD_CER} for phone install")


if __name__ == "__main__":
    main()

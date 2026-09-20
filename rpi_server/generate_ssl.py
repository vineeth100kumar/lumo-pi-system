#!/usr/bin/env python3
"""Generates a self-signed SSL certificate (cert.pem, key.pem)
for HTTPS support on LUMO Smart Controller.
This allows mobile devices (iPhone Safari, Android Chrome) and laptops
to use the device microphone seamlessly without browser security blocks.
"""

import os
import socket
import datetime
import ipaddress
import logging

logger = logging.getLogger("GenerateSSL")

def get_local_ips():
    ips = ["127.0.0.1"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        s.close()
        if primary and primary not in ips:
            ips.append(primary)
    except Exception:
        pass
    return ips

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CERT = os.path.join(BASE_DIR, "cert.pem")
DEFAULT_KEY = os.path.join(BASE_DIR, "key.pem")

def generate_cert(cert_path=None, key_path=None):
    if cert_path is None: cert_path = DEFAULT_CERT
    if key_path is None: key_path = DEFAULT_KEY
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print("[!] cryptography library is not installed. Running openssl fallback...")
        cmd = f'openssl req -x509 -newkey rsa:2048 -keyout "{key_path}" -out "{cert_path}" -days 3650 -nodes -subj "/CN=lumo.local" 2>/dev/null'
        os.system(cmd)
        return os.path.exists(cert_path) and os.path.exists(key_path)

    # 1. Generate RSA 2048 Private Key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )

    # 2. Subject & Issuer
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "lumo.local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LUMO Companion"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Smart Display"),
    ])

    # 3. Subject Alternative Names (SANs) for local IPs and hostnames
    san_list = [
        x509.DNSName("lumo.local"),
        x509.DNSName("localhost")
    ]
    for ip in get_local_ips():
        try:
            san_list.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except Exception:
            pass

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650)) # 10 years
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False
        )
        .sign(private_key, hashes.SHA256())
    )

    # 4. Write Private Key (key.pem)
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # 5. Write Certificate (cert.pem)
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"[OK] Generated SSL Certificate: {cert_path} and {key_path}")
    print(f"     Valid for: lumo.local, localhost, and IPs: {get_local_ips()}")
    return True

if __name__ == "__main__":
    generate_cert()

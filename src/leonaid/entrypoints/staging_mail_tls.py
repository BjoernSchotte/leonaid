"""TLS material for the staging Mailpit relay (profile staging-mail, infra/pilot/compose.yml).

The pilot sends mail only over TLS with certificate verification. On a staging
installation without a real SMTP account, Mailpit plays the relay. This
command writes a private CA (``ca.pem``) and the relay's certificate
(``cert.pem``, ``key.pem``) for one host name. The core worker and Twenty trust
``ca.pem``; nothing else does.

Usage inside the Core image::

    python -m leonaid.entrypoints.staging_mail_tls /smtp mailpit

Idempotent: a certificate for the same host that is valid for more than
30 more days stays, so a restart does not change the CA that running services
already loaded.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PREFIX = "staging-mail-tls"
STAGING_VALIDITY = timedelta(days=397)
RENEW_BEFORE = timedelta(days=30)
FILES = ("ca.pem", "cert.pem", "key.pem")


def write_certificates(
    directory: Path,
    host: str,
    *,
    validity: timedelta = STAGING_VALIDITY,
    ca_common_name: str = "LeonAid staging mail CA",
) -> None:
    """Write a fresh CA and a server certificate for ``host`` to ``directory``."""

    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ca_common_name)])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + validity)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + validity)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    (directory / "ca.pem").write_bytes(ca.public_bytes(pem))
    (directory / "cert.pem").write_bytes(leaf.public_bytes(pem))
    (directory / "key.pem").write_bytes(
        key.private_bytes(
            pem,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    for name in FILES:
        # Mailpit, the core worker and Twenty run as different users; the CA
        # key is never written, so this material signs nothing else.
        (directory / name).chmod(0o644)


def current(directory: Path, host: str, *, now: datetime | None = None) -> bool:
    """True when the existing certificate names ``host`` and stays valid long enough."""

    if not all((directory / name).is_file() for name in FILES):
        return False
    try:
        leaf = x509.load_pem_x509_certificate((directory / "cert.pem").read_bytes())
        names = leaf.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.DNSName)
    except (ValueError, x509.ExtensionNotFound):
        return False
    moment = now or datetime.now(timezone.utc)
    return names == [host] and leaf.not_valid_after_utc - moment > RENEW_BEFORE


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        print(f"{PREFIX}: usage: staging_mail_tls DIRECTORY HOST", file=sys.stderr)
        return 64
    directory, host = Path(arguments[0]), arguments[1]
    if not directory.is_dir():
        print(f"{PREFIX}: ERROR: {directory} is not a directory", file=sys.stderr)
        return 1
    if current(directory, host):
        print(f"{PREFIX}: OK: the certificate for {host} is current")
        return 0
    write_certificates(directory, host)
    print(f"{PREFIX}: OK: wrote a new CA and certificate for {host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

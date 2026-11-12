from __future__ import annotations

import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509

from leonaid.entrypoints.staging_mail_tls import current, main, write_certificates


def test_certificate_is_signed_by_the_written_ca(tmp_path: Path) -> None:
    write_certificates(tmp_path, "mailpit")

    ca = x509.load_pem_x509_certificate((tmp_path / "ca.pem").read_bytes())
    leaf = x509.load_pem_x509_certificate((tmp_path / "cert.pem").read_bytes())
    leaf.verify_directly_issued_by(ca)
    names = leaf.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.DNSName)
    assert names == ["mailpit"]
    # The same files load as a TLS server and as the client's trust anchor.
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "cert.pem", tmp_path / "key.pem")
    client = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
    assert client.cert_store_stats()["x509_ca"] == 1


def test_current_certificate_is_kept(tmp_path: Path) -> None:
    assert main([str(tmp_path), "mailpit"]) == 0
    first = (tmp_path / "ca.pem").read_bytes()

    assert main([str(tmp_path), "mailpit"]) == 0

    assert (tmp_path / "ca.pem").read_bytes() == first


def test_other_host_or_near_expiry_needs_new_certificate(tmp_path: Path) -> None:
    write_certificates(tmp_path, "mailpit")
    now = datetime.now(timezone.utc)

    assert current(tmp_path, "mailpit", now=now)
    assert not current(tmp_path, "relay", now=now)
    assert not current(tmp_path, "mailpit", now=now + timedelta(days=380))


def test_missing_files_or_directory(tmp_path: Path) -> None:
    assert not current(tmp_path, "mailpit")
    assert main([str(tmp_path / "missing"), "mailpit"]) == 1
    assert main([str(tmp_path)]) == 64

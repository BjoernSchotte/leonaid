#!/usr/bin/env python3
"""Validate a private pilot mail expectation against real public DNS."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Literal

import dns.exception
import dns.resolver

SCHEMA = "leonaid.mail-domain-readiness/v1"
EXPECTATION_SCHEMA = "leonaid.mail-domain-expectation/v1"
DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
SELECTOR = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,61}[a-z0-9])?$")
DmarcPolicy = Literal["quarantine", "reject"]


class MailDomainError(RuntimeError):
    """A stable, payload-free mail-domain readiness error."""


@dataclass(frozen=True)
class Expectation:
    domain: str
    dkim_selector: str
    dkim_key_type: str
    dmarc_policy: DmarcPolicy
    envelope_from: str
    visible_from: str
    reply_to: str
    spf_required_terms: tuple[str, ...]


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MailDomainError(f"expectation_{key}_invalid")
    return value.strip()


def load_expectation(path: Path) -> Expectation:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MailDomainError("expectation_unreadable") from error
    if not isinstance(payload, dict):
        raise MailDomainError("expectation_object_required")
    if payload.get("schemaVersion") != EXPECTATION_SCHEMA:
        raise MailDomainError("expectation_schema_invalid")

    domain = _required_text(payload, "domain").casefold().rstrip(".")
    selector = _required_text(payload, "dkimSelector").casefold()
    key_type = _required_text(payload, "dkimKeyType").casefold()
    policy = _required_text(payload, "dmarcPolicy").casefold()
    terms = payload.get("spfRequiredTerms")
    if not DOMAIN.fullmatch(domain):
        raise MailDomainError("expectation_domain_invalid")
    if not SELECTOR.fullmatch(selector):
        raise MailDomainError("expectation_dkim_selector_invalid")
    if key_type not in {"rsa", "ed25519"}:
        raise MailDomainError("expectation_dkim_key_type_invalid")
    if policy not in {"quarantine", "reject"}:
        raise MailDomainError("expectation_dmarc_policy_invalid")
    if (
        not isinstance(terms, list)
        or not terms
        or any(not isinstance(term, str) or not term.strip() for term in terms)
    ):
        raise MailDomainError("expectation_spf_terms_invalid")
    return Expectation(
        domain=domain,
        dkim_selector=selector,
        dkim_key_type=key_type,
        dmarc_policy=policy,  # type: ignore[arg-type]
        envelope_from=_required_text(payload, "envelopeFrom"),
        visible_from=_required_text(payload, "visibleFrom"),
        reply_to=_required_text(payload, "replyTo"),
        spf_required_terms=tuple(str(term).strip() for term in terms),
    )


def _mail_domain(value: str, *, error_code: str) -> str:
    _label, address = parseaddr(value)
    if address.count("@") != 1:
        raise MailDomainError(error_code)
    local, domain = address.rsplit("@", 1)
    normalized = domain.casefold().rstrip(".")
    if not local or not DOMAIN.fullmatch(normalized):
        raise MailDomainError(error_code)
    return normalized


def _aligned(actual: str, expected: str) -> bool:
    return actual == expected or actual.endswith(f".{expected}")


def validate_identities(expectation: Expectation) -> dict[str, bool]:
    identities = {
        "envelopeFromAligned": _aligned(
            _mail_domain(
                expectation.envelope_from,
                error_code="envelope_from_invalid",
            ),
            expectation.domain,
        ),
        "replyToAligned": _aligned(
            _mail_domain(expectation.reply_to, error_code="reply_to_invalid"),
            expectation.domain,
        ),
        "visibleFromAligned": _aligned(
            _mail_domain(
                expectation.visible_from,
                error_code="visible_from_invalid",
            ),
            expectation.domain,
        ),
    }
    for key, value in identities.items():
        if not value:
            code = {
                "envelopeFromAligned": "envelope_from_not_aligned",
                "replyToAligned": "reply_to_not_aligned",
                "visibleFromAligned": "visible_from_not_aligned",
            }[key]
            raise MailDomainError(code)
    return identities


def _txt_value(record: Any) -> str:
    strings = getattr(record, "strings", None)
    if not isinstance(strings, tuple):
        raise MailDomainError("dns_txt_record_invalid")
    try:
        return b"".join(strings).decode("utf-8")
    except UnicodeDecodeError as error:
        raise MailDomainError("dns_txt_record_invalid") from error


def _query_txt(
    resolver: dns.resolver.Resolver,
    name: str,
) -> tuple[str, ...]:
    for attempt in range(3):
        try:
            answer = resolver.resolve(name, "TXT", lifetime=5)
            values = tuple(_txt_value(record) for record in answer)
            if not values:
                raise MailDomainError("dns_txt_record_missing")
            return values
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer) as error:
            raise MailDomainError("dns_txt_record_missing") from error
        except (dns.exception.Timeout, dns.resolver.NoNameservers) as error:
            if attempt == 2:
                raise MailDomainError("dns_resolver_unavailable") from error
    raise MailDomainError("dns_resolver_unavailable")


def resolve_records(
    expectation: Expectation,
    *,
    nameservers: tuple[str, ...] = (),
    port: int = 53,
) -> dict[str, tuple[str, ...]]:
    resolver = dns.resolver.Resolver(configure=not nameservers)
    if nameservers:
        resolver.nameservers = list(nameservers)
    resolver.port = port
    return {
        "spf": _query_txt(resolver, expectation.domain),
        "dkim": _query_txt(
            resolver,
            f"{expectation.dkim_selector}._domainkey.{expectation.domain}",
        ),
        "dmarc": _query_txt(resolver, f"_dmarc.{expectation.domain}"),
    }


def _single_prefixed(
    values: tuple[str, ...],
    prefix: str,
    *,
    missing: str,
    multiple: str,
) -> str:
    matching = [value for value in values if value.casefold().startswith(prefix)]
    if not matching:
        raise MailDomainError(missing)
    if len(matching) != 1:
        raise MailDomainError(multiple)
    return matching[0]


def _tags(record: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in record.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator:
            result[key.casefold()] = value.strip()
    return result


def validate_records(
    expectation: Expectation,
    records: dict[str, tuple[str, ...]],
) -> None:
    spf = _single_prefixed(
        records["spf"],
        "v=spf1",
        missing="spf_record_missing",
        multiple="spf_record_multiple",
    )
    spf_terms = spf.split()
    for term in expectation.spf_required_terms:
        if term not in spf_terms:
            raise MailDomainError("spf_required_term_missing")
    if not spf_terms or spf_terms[-1] not in {"-all", "~all"}:
        raise MailDomainError("spf_terminal_policy_invalid")

    dkim = _single_prefixed(
        records["dkim"],
        "v=dkim1",
        missing="dkim_record_missing",
        multiple="dkim_record_multiple",
    )
    dkim_tags = _tags(dkim)
    if dkim_tags.get("k", "rsa").casefold() != expectation.dkim_key_type:
        raise MailDomainError("dkim_key_type_mismatch")
    if len(dkim_tags.get("p", "")) < 32:
        raise MailDomainError("dkim_public_key_missing")

    dmarc = _single_prefixed(
        records["dmarc"],
        "v=dmarc1",
        missing="dmarc_record_missing",
        multiple="dmarc_record_multiple",
    )
    dmarc_tags = _tags(dmarc)
    if dmarc_tags.get("p", "").casefold() != expectation.dmarc_policy:
        raise MailDomainError("dmarc_policy_mismatch")
    if dmarc_tags.get("pct", "100") != "100":
        raise MailDomainError("dmarc_coverage_incomplete")


def _fingerprint(values: tuple[str, ...]) -> str:
    canonical = "\n".join(sorted(values)).encode()
    return hashlib.sha256(canonical).hexdigest()


def checksum_report(report: dict[str, Any]) -> str:
    canonical = json.dumps(
        report,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def assess(
    expectation: Expectation,
    records: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    identities = validate_identities(expectation)
    validate_records(expectation, records)
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "status": "ready",
        "domain": expectation.domain,
        "dkimSelector": expectation.dkim_selector,
        "identities": identities,
        "dns": {
            key: {
                "fingerprintSha256": _fingerprint(value),
                "recordCount": len(value),
                "valid": True,
            }
            for key, value in sorted(records.items())
        },
    }
    report["checksumSha256"] = checksum_report(report)
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prüft bestätigte Mailidentitäten sowie SPF, DKIM und DMARC "
            "gegen echte DNS-TXT-Antworten."
        )
    )
    parser.add_argument("--expectation", type=Path, required=True)
    parser.add_argument("--nameserver", action="append", default=[])
    parser.add_argument("--port", type=int, default=53)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    try:
        expectation = load_expectation(arguments.expectation.resolve())
        records = resolve_records(
            expectation,
            nameservers=tuple(arguments.nameserver),
            port=arguments.port,
        )
        report = assess(expectation, records)
    except MailDomainError as error:
        print(f"mail-domain-check: BLOCKED: {error}", file=sys.stderr)
        return 2
    if arguments.report is not None:
        write_report(arguments.report.resolve(), report)
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print(
            "mail-domain-check: READY: Absenderausrichtung, SPF, DKIM und "
            f"DMARC für {report['domain']} über echten DNS-Resolver bewiesen"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

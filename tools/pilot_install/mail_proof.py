#!/usr/bin/env python3
"""Real-system mail proof for ./leonaid test-pilot-install.

The pilot's SMTP relay is played by Mailpit with implicit TLS (port 465), SMTP
AUTH required and a certificate from a throwaway test CA. The subcommands run in
different containers of the isolated test project:

- ``certificates DIR`` (core image): write the test CA and the relay's
  certificate for MAIL_SMTP_HOST;
- ``core-send RECIPIENT`` (inside the running worker, script on stdin): send
  one message through the core's own SMTP transport and production settings;
- ``twenty-reset EMAIL`` (inside the running api, script on stdin): ask Twenty
  for a password reset link, which Twenty's worker sends by mail;
- ``assert-delivered API RECIPIENT FROM SUBJECT_WORD`` (Python image on the
  egress network): wait until Mailpit accepted that message.

Nothing here prints credentials or message bodies.
"""

from __future__ import annotations

import json
import re
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path


def certificates(directory: Path, host: str) -> None:
    from leonaid.entrypoints.staging_mail_tls import write_certificates

    write_certificates(
        directory,
        host,
        validity=timedelta(days=1),
        ca_common_name="LeonAid pilot-install test CA",
    )


def core_send(recipient: str) -> None:
    from email.message import EmailMessage

    from leonaid.adapters.mail.transport import SmtpTransport
    from leonaid.configuration import load_mail_transport_settings

    settings = load_mail_transport_settings()
    transport = SmtpTransport(
        host=settings.host,
        port=settings.port,
        sender=settings.sender,
        mode=settings.mode,
        username=settings.username,
        password=(
            settings.password.get_secret_value()
            if settings.password is not None
            else None
        ),
        timeout_seconds=settings.timeout_seconds,
        verify_certificates=settings.verify_certificates,
        ca_file=settings.ca_file,
        envelope_from=settings.envelope_from,
        reply_to=settings.reply_to,
    )
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = recipient
    message["Subject"] = "LeonAid pilot-install relay probe"
    message.set_content("Relay probe from the core worker.")
    transport.send(message)
    print(f"mail-proof: core worker sent through {settings.safe_summary()['mode']}")


def twenty_reset(email: str) -> None:
    body = json.dumps(
        {
            "query": "mutation Reset($email: String!) { "
            "emailPasswordResetLink(email: $email) { success } }",
            "variables": {"email": email},
        }
    ).encode()
    # Twenty serves its auth mutations on /metadata and resolves the
    # workspace from the browser origin, like its own sign-in page.
    request = urllib.request.Request(
        os.environ["TWENTY_BASE_URL"] + "/metadata",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Origin": os.environ["TWENTY_ORIGIN"],
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    result = (payload.get("data") or {}).get("emailPasswordResetLink") or {}
    if result.get("success") is not True:
        # Twenty's auth errors carry no secrets; show code and message.
        problems = [
            (
                (error.get("extensions") or {}).get("code"),
                (error.get("extensions") or {}).get("subCode"),
                str(error.get("message", ""))[:200],
            )
            for error in payload.get("errors") or []
        ]
        raise SystemExit(f"mail-proof: Twenty refused the reset request: {problems}")
    print("mail-proof: Twenty accepted the password reset request")


def mailbox(address: str) -> str:
    """Local part only: the public CI evidence rejects every e-mail address."""
    return address.partition("@")[0]


def assert_delivered(api: str, recipient: str, sender: str, word: str) -> None:
    query = urllib.parse.urlencode({"query": f"to:{recipient}"})
    deadline = time.monotonic() + 90
    while True:
        with urllib.request.urlopen(
            f"{api}/api/v1/search?{query}", timeout=10
        ) as response:
            messages = json.loads(response.read()).get("messages") or []
        for message in messages:
            if (message.get("From") or {}).get("Address") == sender and word in (
                message.get("Subject") or ""
            ):
                print(
                    f"mail-proof: relay accepted '{message['Subject']}' "
                    f"from {mailbox(sender)} for {mailbox(recipient)}"
                )
                return
        if time.monotonic() > deadline:
            raise SystemExit(
                f"mail-proof: no message from {mailbox(sender)} for "
                f"{mailbox(recipient)} with '{word}' in the subject; "
                f"{len(messages)} other message(s)"
            )
        time.sleep(2)


def login_mails(api: str, recipient: str) -> list[dict[str, object]]:
    query = urllib.parse.urlencode({"query": f"to:{recipient} subject:LeonAid-Login"})
    with urllib.request.urlopen(f"{api}/api/v1/search?{query}", timeout=10) as response:
        return json.loads(response.read()).get("messages") or []


def login_count(api: str, recipient: str) -> None:
    print(len(login_mails(api, recipient)))


def login_code(api: str, recipient: str, minimum: str = "1") -> None:
    """Print the code of the newest sign-in mail for recipient (test relay only).

    Waits until at least `minimum` sign-in mails arrived, so a code requested
    just now is not confused with an older one."""
    query = urllib.parse.urlencode({"query": f"to:{recipient} subject:LeonAid-Login"})
    deadline = time.monotonic() + 90
    while True:
        with urllib.request.urlopen(
            f"{api}/api/v1/search?{query}", timeout=10
        ) as response:
            messages = json.loads(response.read()).get("messages") or []
        if len(messages) >= int(minimum):
            newest = max(messages, key=lambda message: message.get("Created") or "")
            with urllib.request.urlopen(
                f"{api}/api/v1/message/{newest['ID']}", timeout=10
            ) as response:
                text = json.loads(response.read()).get("Text") or ""
            match = re.search(r"den Code ([0-9]{6}) verwenden", text)
            if match is None:
                raise SystemExit("mail-proof: the sign-in mail carries no code")
            print(match.group(1))
            return
        if time.monotonic() > deadline:
            raise SystemExit(f"mail-proof: no sign-in mail for {mailbox(recipient)}")
        time.sleep(2)


def main() -> None:
    command, *arguments = sys.argv[1:]
    if command == "certificates":
        certificates(Path(arguments[0]), arguments[1])
    elif command == "core-send":
        core_send(arguments[0])
    elif command == "twenty-reset":
        twenty_reset(arguments[0])
    elif command == "assert-delivered":
        assert_delivered(*arguments)
    elif command == "login-code":
        login_code(*arguments)
    elif command == "login-count":
        login_count(*arguments)
    else:
        raise SystemExit(f"mail-proof: unknown command {command}")


if __name__ == "__main__":
    main()

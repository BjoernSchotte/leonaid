"""Verify real public HTML keeps Inbox availability independent of ordering."""

import argparse
import json
import ssl
from html.parser import HTMLParser
from pathlib import Path

import httpx


class InboxForms(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action_ids: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "leonaid-inbox-form":
            self.action_ids.append(dict(attrs).get("data-action-id"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    active, inactive = fixture["active"], fixture["inactive"]
    with httpx.Client(
        base_url=args.base_url,
        verify=ssl.create_default_context(cafile=str(args.ca)),
        timeout=15,
    ) as client:
        route = client.get(f"/api/v1/public/actions/alias/{active['alias']}")
        route.raise_for_status()
        current = route.json()
        assert current["availability"] == "published"
        assert current["action"]["id"] == active["id"]
        assert current["submissionsAllowed"] is False
        assert current["action"]["orderForm"] is None
        for path, expected in (
            ("/", [None]),
            (f"/{active['alias']}", [active["id"]]),
            (f"/archive/{active['slug']}", []),
            (f"/{inactive['alias']}", []),
        ):
            response = client.get(path)
            response.raise_for_status()
            forms = InboxForms()
            forms.feed(response.text)
            assert forms.action_ids == expected, (path, forms.action_ids, expected)
            if expected:
                assert 'name="subject"' in response.text
                assert 'name="message"' in response.text
            print(f"PASS {path}: {len(forms.action_ids)} Inbox form(s)")


if __name__ == "__main__":
    main()

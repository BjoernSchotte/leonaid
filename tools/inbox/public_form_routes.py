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
    parser.add_argument(
        "--campaign",
        action="store_true",
        help="Require published CMS content for the active fixture",
    )
    parser.add_argument(
        "--campaign-alias",
        action="store_true",
        help="Require alias redirect to the published CMS campaign",
    )
    args = parser.parse_args()
    if args.campaign_alias and not args.campaign:
        parser.error("--campaign-alias requires --campaign")
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
        campaign = client.get(f"/api/v1/public/actions/campaign/{active['slug']}")
        campaign.raise_for_status()
        assert campaign.json()["action"]["id"] == active["id"]
        assert campaign.json()["submissionsAllowed"] is False
        paths = [
            ("/", [None]),
            (f"/archive/{active['slug']}", []),
            (f"/{inactive['alias']}", []),
        ]
        if args.campaign_alias:
            alias_path = f"/{active['alias']}"
            for method in ("GET", "HEAD"):
                redirected = client.request(method, alias_path)
                assert redirected.status_code == 302
                assert redirected.headers["location"] == f"/campaigns/{active['slug']}/"
                print(f"PASS {method} {alias_path}: campaign redirect")
        else:
            paths.append((f"/{active['alias']}", [active["id"]]))
        if args.campaign:
            canonical = f"/campaigns/{active['slug']}/"
            redirect = client.get(canonical.rstrip("/"))
            assert redirect.status_code == 308
            assert redirect.headers["location"] == canonical
            paths.append((canonical, [active["id"]]))
        for path, expected in paths:
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

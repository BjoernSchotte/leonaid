"""Fail when an adapted Caddy config compresses anything but build assets.

Reads `caddy adapt` JSON on stdin. Every `encode` handler must sit in a route
whose only matcher is a path list from the build-asset prefixes, and may only
match static asset content types. HTML, JSON and dynamic routes stay plain
(BREACH).
"""

import json
import sys

ALLOWED_PATHS = {
    "/assets/*",
    "/manifest.webmanifest",
    "/_astro/*",
    "/_campaign-assets/*",
}
ALLOWED_TYPES = {
    "text/javascript*",
    "application/javascript*",
    "text/css*",
    "image/svg+xml*",
    "application/manifest+json*",
}


def routes(node):
    if isinstance(node, dict):
        if isinstance(node.get("handle"), list):
            yield node
        for value in node.values():
            yield from routes(value)
    elif isinstance(node, list):
        for value in node:
            yield from routes(value)


def problems(config):
    found = []
    for route in routes(config):
        for handler in route["handle"]:
            if not isinstance(handler, dict) or handler.get("handler") != "encode":
                continue
            matchers = route.get("match") or []
            paths = [path for matcher in matchers for path in matcher.get("path", [])]
            if (
                not matchers
                or any(set(matcher) != {"path"} for matcher in matchers)
                or not set(paths) <= ALLOWED_PATHS
            ):
                found.append(f"encode outside build-asset prefixes: {matchers}")
            response = handler.get("match") or {}
            types = set(response.get("headers", {}).get("Content-Type", []))
            if set(response) != {"headers"} or not types or not types <= ALLOWED_TYPES:
                found.append(f"encode for non-asset content types: {response}")
    return found


def main():
    name = sys.argv[1]
    found = problems(json.load(sys.stdin))
    for problem in found:
        print(f"caddyfile-check: ERROR: {name}: {problem}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())

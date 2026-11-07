"""Static guards for the Content-Security-Policy.

Caddy sends the policy for the static apps and the API; the Astro apps send
their own policy with sha256 hashes. Both sources must agree on every directive
except script-src/style-src, and no source may allow inline code. The browser
suites prove the resulting pages raise no CSP violations.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CADDYFILES = (
    "infra/proxy/Caddyfile",
    "infra/proxy/Caddyfile.split",
    "infra/pilot/Caddyfile",
    "infra/pilot/Caddyfile.split",
    "infra/pilot/Caddyfile.test",
)
ASTRO_CONFIGS = ("apps/public/astro.config.mjs", "apps/campaign-site/astro.config.mjs")
UNSAFE = ("'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'", "'strict-dynamic'")


def _directives(policy: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in policy.split(";"):
        tokens = part.split()
        if tokens:
            assert tokens[0] not in result, f"duplicate directive {tokens[0]}"
            result[tokens[0]] = " ".join(tokens[1:])
    return result


def _snippet_policy(caddyfile: str, snippet: str) -> tuple[str, str]:
    text = (ROOT / caddyfile).read_text(encoding="utf-8")
    block = re.search(rf"^\({snippet}\) \{{\n(.*?)^\}}", text, re.M | re.S)
    assert block, f"{caddyfile} lacks ({snippet})"
    match = re.search(
        r'^\s*([?+]?)Content-Security-Policy "([^"]+)"', block.group(1), re.M
    )
    assert match, f"{caddyfile} ({snippet}) lacks a Content-Security-Policy"
    return match.group(1), match.group(2)


def _astro_directives(config: str) -> dict[str, str]:
    text = (ROOT / config).read_text(encoding="utf-8")
    csp = re.search(r"csp: \{(.*?)\n    \},", text, re.S)
    assert csp, f"{config} does not enable security.csp"
    body = csp.group(1)
    assert "'unsafe-" not in body
    listed = re.search(r"directives: \[(.*?)\]", body, re.S)
    assert listed, f"{config} lists no CSP directives"
    return _directives(";".join(re.findall(r'"([^"]+)"', listed.group(1))))


@pytest.mark.parametrize("caddyfile", CADDYFILES)
def test_caddy_policies_are_strict_and_identical(caddyfile: str) -> None:
    strict_prefix, strict = _snippet_policy(caddyfile, "leonaid_headers")
    astro_prefix, astro = _snippet_policy(caddyfile, "astro_headers")
    # Caddy enforces its policy for static apps, but only fills it in where an
    # Astro response carries none; a second policy would block hashed scripts.
    assert strict_prefix == ""
    assert astro_prefix == "?"
    assert strict == astro
    directives = _directives(strict)
    assert directives["script-src"] == "'self'"
    assert directives["style-src"] == "'self'"
    assert directives["object-src"] == "'none'"
    assert directives["frame-ancestors"] == "'none'"
    for token in UNSAFE:
        assert token not in strict
    # Scheme-wide sources would allow any host.
    assert not re.search(
        r"(^|\s)(ws|wss|https?|data|blob):(\s|$)", directives["connect-src"]
    )
    # No other route may define its own, weaker policy.
    policy_lines = [
        line
        for line in (ROOT / caddyfile).read_text(encoding="utf-8").splitlines()
        if re.match(r'\s*[?+]?Content-Security-Policy "', line)
    ]
    assert len(policy_lines) == 2


def test_all_caddyfiles_send_the_same_policy() -> None:
    policies = {
        caddyfile: _snippet_policy(caddyfile, "leonaid_headers")[1]
        for caddyfile in CADDYFILES
    }
    assert len(set(policies.values())) == 1, policies


@pytest.mark.parametrize("config", ASTRO_CONFIGS)
def test_astro_policy_matches_caddy_except_hashed_sources(config: str) -> None:
    caddy = _directives(_snippet_policy(CADDYFILES[0], "leonaid_headers")[1])
    caddy.pop("script-src")
    caddy.pop("style-src")
    assert _astro_directives(config) == caddy


@pytest.mark.parametrize("caddyfile", CADDYFILES)
def test_astro_served_routes_use_the_fallback_policy(caddyfile: str) -> None:
    text = (ROOT / caddyfile).read_text(encoding="utf-8")
    # The catch-all handle proxies the public Astro app.
    for handle in re.findall(r"\n\thandle \{\n(.*?)\n\t\}", text, re.S):
        if "reverse_proxy public:3000" in handle:
            assert "import astro_headers" in handle
            assert "import leonaid_headers" not in handle
    for handle in re.findall(
        r"\n\thandle @campaign_routes \{\n(.*?)\n\t\}", text, re.S
    ):
        assert "import astro_headers" in handle
        assert "import leonaid_headers" not in handle
    for prefix, upstream in (("/app/*", "pwa:3000"), ("/admin/*", "web:3000")):
        block = re.search(
            rf"\n\thandle_path {re.escape(prefix)} \{{\n(.*?)\n\t\}}", text, re.S
        )
        assert block and upstream in block.group(1)
        assert "import leonaid_headers" in block.group(1)


class _InlineCode(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.findings: list[str] = []
        self._in_inline_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = {name for name, _ in attrs}
        if tag == "script" and "src" not in names:
            self._in_inline_script = True
        if tag == "style":
            self.findings.append("<style>")
        if "style" in names:
            self.findings.append(f"style attribute on <{tag}>")
        self.findings.extend(
            f"{name} handler on <{tag}>" for name in names if name.startswith("on")
        )

    def handle_endtag(self, tag: str) -> None:
        self._in_inline_script = False

    def handle_data(self, data: str) -> None:
        if self._in_inline_script and data.strip():
            self.findings.append("inline <script>")


@pytest.mark.parametrize(
    "document",
    ("apps/web/index.html", "apps/pwa/index.html", "apps/pwa/public/offline.html"),
)
def test_static_documents_carry_no_inline_code(document: str) -> None:
    parser = _InlineCode()
    parser.feed((ROOT / document).read_text(encoding="utf-8"))
    assert parser.findings == []


def test_static_server_serves_the_external_boot_files() -> None:
    server = (ROOT / "infra/compose/static-server.mjs").read_text(encoding="utf-8")
    web = re.search(r"web: new Set\(\[(.*?)\]\)", server, re.S)
    pwa = re.search(r"pwa: new Set\(\[(.*?)\]\)", server, re.S)
    assert web and '"/theme-init.js"' in web.group(1)
    assert pwa
    for file in ('"/theme-init.js"', '"/offline.css"', '"/offline.js"'):
        assert file in pwa.group(1)
    for app in ("web", "pwa"):
        assert (ROOT / f"apps/{app}/public/theme-init.js").is_file()
    worker = (ROOT / "apps/pwa/public/sw.js").read_text(encoding="utf-8")
    for file in ("/app/offline.css", "/app/offline.js", "/app/theme-init.js"):
        assert f'"{file}"' in worker

# Reproduzierbare Abhängigkeiten

`external-systems.lock` ist die kanonische, maschinenlesbare Liste aller
externen Systeme sowie aller Container, die den PoC bauen oder prüfen. Ein
Eintrag enthält immer einen lesbaren Tag und den unveränderlichen
Multi-Arch-Index-Digest. Compose- und Dockerfile-Referenzen müssen dieselbe
Form `image:version@sha256:digest` verwenden.

`browser-artifacts.lock` hält zusätzlich die im Playwright-Image enthaltenen
Browser-Revisionen fest. `uv.lock` und `bun.lock` sind die kanonischen
Paket-Locks. Die Toolchain-Versionen stehen in `.tool-versions`.

Die React-Peers von `packages/surveys` deklarieren als eng begrenzte Ausnahme
den Kompatibilitätsbereich `^19.2.8`. Der Pin-Checker erlaubt dies ausschließlich
für `react` und `react-dom` im Peer-Abschnitt dieses Packages. Alle LeonAid-Hosts,
die das Package direkt einbinden, müssen beide Laufzeitabhängigkeiten exakt auf
`19.2.8` setzen. Andere Packages und Abhängigkeitsabschnitte bleiben exakt gepinnt.
Der unabhängige Consumer prüft zusätzlich die tatsächlichen installierten
Versionen und verwendet seinen eigenen Frozen Lockfile. Ein Versionswechsel
benötigt eine gemeinsame Aktualisierung dieser Policy, der Hosts und Locks sowie
einen erneuten Consumer-Test. Der Peer-Bereich allein ist kein Testnachweis für
zukünftige React-Versionen.

Updates erfolgen ausschließlich in einem expliziten Renovate-PR oder einem
manuell eröffneten Upgrade-PR. Ein solcher PR aktualisiert Tag und Digest,
setzt `reviewedAt` sowie `nextReviewOn`, erzeugt alle Locks und SBOMs neu und
durchläuft die Contract- und E2E-Gates. Automerges sind deaktiviert.

## Review deadline and vulnerability gates

`tools/pins/check.py` fails once `nextReviewOn` lies in the past, and it
rejects a `nextReviewOn` more than six months after `reviewedAt`. A review
compares every pinned tag with its latest upstream release and advisories,
upgrades or consciously keeps it, and runs `./leonaid check` and
`tools/ci/security.sh`. Then set `reviewedAt` to the review date and
`nextReviewOn` to at most three months later.

Every system in this lock must be classified in
`infra/security/image-scan-scope.json`: scanned as a runtime image, or
excluded with a kind and a reason. `tools/security/vulnerability-scan.sh`
blocks fixable HIGH/CRITICAL findings in the checkout, all LeonAid images,
the scanned third-party images (Trivy) and in `uv.lock`/`bun.lock`
(OSV-Scanner). Findings without an upstream fix go into
`infra/security/vulnerability-allowlist.json` with reason, reviewer and an
expiry at most 90 days after the review; expired waivers fail the gate.

Die Prüfungen werden ausschließlich in den hier erfassten Docker-Images
ausgeführt:

```sh
docker run --rm -v "$PWD:/workspace:ro" \
  python:3.13.18-slim-trixie@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1 \
  python /workspace/tools/pins/check.py /workspace
```

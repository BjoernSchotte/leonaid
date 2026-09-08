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

Die Prüfungen werden ausschließlich in den hier erfassten Docker-Images
ausgeführt:

```sh
docker run --rm -v "$PWD:/workspace:ro" \
  python:3.13.13-slim-trixie@sha256:aa938a849bcb82dce8f49480f056ab82bf5c1c3ebc294f0430f37b6820e7f286 \
  python /workspace/tools/pins/check.py /workspace
```

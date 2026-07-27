# LeonAid — Charity-Verwaltung für Service Clubs

Open-Source-Plattform für die Charity-Arbeit von Service Clubs. Der geplante
PoC verbindet verteilte Sponsoren-Akquise, aktionsbezogene Abwicklung und
Ausgangsrechnungen. Er ersetzt die bisherigen, manuellen Excel-Listen.

- **Charity-Admins** verwalten Aktionen, Akquisiteure, Bestellungen und
  Rechnungsabläufe. Ein PoC-Spike klärt, wie weit Twenty dafür als
  Admin-Oberfläche reicht.
- **Akquisiteure** nutzen eine schlanke **PWA** für ihre zugeordneten Aktionen,
  Firmen, Wiedervorlagen und Zusagen.
- Aktionsspezifische Rollen wie **Ausfahrer** können später über optionale
  Capabilities ergänzt werden.

## Status

🟡 **PoC in Umsetzung.** Der technische Plan wird taskweise umgesetzt. Ein
Task wird erst nach realen, Docker-basierten Nachweisen abgehakt, committed
und direkt auf `main` gepusht.

## Lokaler Einstieg

Voraussetzung ist ausschließlich eine laufende Docker-Umgebung wie OrbStack.
Projektpakete müssen nicht global installiert werden.

```sh
./leonaid bootstrap
./leonaid doctor
./leonaid check
```

`bootstrap` erzeugt `.env.local`, installiert die exakt gelockten Python- und
Frontend-Pakete in den digest-gepinnten Containern und ruft anschließend
`doctor` auf. Die lokalen Twenty-Admin-Zugangsdaten stehen ausschließlich in
der ignorierten Datei `.env.local` unter `TWENTY_BOOTSTRAP_EMAIL` und
`TWENTY_BOOTSTRAP_PASSWORD`; sie werden nie geloggt oder committed.

Der reale Golden-Stack lässt sich anschließend reproduzierbar bedienen:

```sh
./leonaid dev
./leonaid seed
./leonaid snapshot
./leonaid reset
```

`reset` löscht ausschließlich ein explizit freigegebenes lokales LeonAid-
Compose-Projekt und stellt Core-PostgreSQL, Twenty, RustFS und Mailpit auf
Golden Data v1 wieder her. Verfügbare und für spätere Meilensteine bereits
reservierte Befehle zeigt `./leonaid help`.

Der kanonische HTTP-Vertrag und der gemeinsame TypeScript-Client werden mit
`./leonaid generate-api-client` gemeinsam aus FastAPI regeneriert.

## Dokumente

- [Personas und Rollen](PERSONAS.md) — zentrale, bei Rollen-, Rechte- und
  UX-Änderungen verbindlich mitzuführende Produktreferenz.
- [Produkt- und Architekturvorschlag](specs/produkt-und-architekturvorschlag.md) —
  neues Zielbild mit PoC-Schnitt, Systemgrenzen, Compose-Profilen und Capability-Landkarte.
- [Architektur & Design](specs/architektur.md) — bisheriger, engerer Entwurf für
  den reinen Akquise-PoC; wird anhand des neuen Zielbilds neu bewertet.
- [Technischer Implementierungsplan](specs/leonaid-poc/PLAN.md) — abhakbare
  Tasks, Akzeptanzkriterien und reale Tests.
- [Development Guide](specs/leonaid-poc/DEVELOPMENT.md) — Docker-Workflow,
  Editor, Debugging und Fehlerdiagnose.

## Eckdaten der Lösung (Kurzfassung)

|                         |                                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------------------- |
| **Backend**             | [Twenty CRM](https://github.com/twentyhq/twenty) (Open Source, AGPL-3.0), self-hosted             |
| **Operatives Frontend** | React/TypeScript-PWA, shadcn/ui, freie Hugeicons; gemeinsame App Shell                            |
| **LeonAid Core**        | Python 3.13, FastAPI, frameworkfreie Application Services und transaktionaler Outbox-Worker       |
| **ERP-light**           | Bestellungen, Ausgangsrechnungen, Typst-PDF und manueller Zahlungsstatus                          |
| **Public Web**          | Astro 7 als Teil des Core; zeitlich begrenzte Aktionsseiten und aktionsbezogene Standardformulare |
| **Kommunikation**       | externer Mail-Relay; optionales listmonk-Compose-Profil                                           |
| **Hosting**             | Hetzner (EU → DSGVO-sauber), Docker Compose, TLS via Caddy                                        |
| **Team**                | 2 Personen (Infra/Backend + Frontend/UX)                                                          |

## Warum nicht Twenty direkt am Handy?

Twenty ist ein flexibles CRM, aber keine auf operative Rollen zugeschnittene
PWA. Das freie Self-hosted Twenty bietet zudem keine Row-Level Permissions.
Deshalb greifen diese Rollen ausschließlich über die eigene PWA und die
serverseitige LeonAid-Autorisierung zu.

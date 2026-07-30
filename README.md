# LeonAid — Charity-Verwaltung für Service Clubs

Plattform für die Charity-Arbeit von Service Clubs. Der geplante PoC verbindet
verteilte Sponsoren-Akquise, aktionsbezogene Abwicklung und
Ausgangsrechnungen. Er ersetzt die bisherigen, manuellen Excel-Listen.

- **Charity-Admins** verwalten Aktionen, Akquisiteure, Bestellungen und
  Rechnungsabläufe. Ein PoC-Spike klärt, wie weit Twenty dafür als
  Admin-Oberfläche reicht.
- **Akquisiteure** nutzen eine schlanke **PWA** für ihre zugeordneten Aktionen,
  Firmen, Wiedervorlagen und Zusagen.
- Aktionsspezifische Rollen wie **Ausfahrer** können später über optionale
  Capabilities ergänzt werden.

## Status

🟢 **Krapfentaxi-PoC vollständig bewiesen und fachlich abgenommen.** Die
vollständige Journey läuft ohne Mocks in Chromium, Firefox und WebKit sowie
nach einem leeren Golden Reset. Der Produktverantwortliche hat den
beschriebenen PoC-Schnitt am 28. Juli 2026 freigegeben und das zusätzliche
personenbezogene Fresh-Checkout-Gate für diesen PoC-Abschluss aufgehoben.

## Lizenz

**Status: `UNDEFINED`.** Für LeonAid wurde noch keine Projektlizenz
festgelegt. Der Repository-Inhalt ist daher derzeit nicht als
Open-Source-Software lizenziert. [`LICENSE`](LICENSE) hält diesen
Zwischenstand ausdrücklich fest; die gesonderten Lizenzen und Hinweise der
verwendeten Drittanbieter-Komponenten bleiben davon unberührt.

## In höchstens 30 Minuten zur Golden Journey

Voraussetzung ist ausschließlich eine laufende Docker-Umgebung wie OrbStack.
Projektpakete müssen nicht global installiert werden.

### Minute 0–8: Checkout vorbereiten

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

### Minute 8–18: realen Stack und Golden Data starten

```sh
./leonaid dev
./leonaid seed
```

Der Start ist fertig, wenn `dev: OK` und `golden-seed: OK` erscheinen.
`seed` provisioniert das deklarative Twenty-Schema und einen verifizierten
Least-Privilege-Key, startet API und Worker mit diesem Key neu und spielt
danach Golden Data idempotent in die realen Systeme ein.
Für eine isolierte Schema-/Key-Wartung ohne Golden Seed bleibt
`./leonaid provision-twenty` als expliziter Operatorbefehl verfügbar.

| Oberfläche         | Lokale Adresse                      |
| ------------------ | ----------------------------------- |
| öffentliche Aktion | <http://127.0.0.1:8080/krapfentaxi> |
| Mitglieder-Login   | <http://127.0.0.1:8080/login>       |
| Admin-Portal       | <http://127.0.0.1:8080/admin/>      |
| Akquisiteur-PWA    | <http://127.0.0.1:8080/app/>        |
| Twenty             | <http://crm.localhost:8080>         |
| lokale Testmails   | <http://127.0.0.1:8080/mail/>       |

Die synthetischen Persona-Adressen stehen in
[`tests/fixtures/golden/v1`](tests/fixtures/golden/v1/README.md).
Login-Codes kommen über den echten Mailpfad in Mailpit. Zusätzlich erzeugen
`seed` und `reset` aus dem Golden Dataset die ignorierte
`.local/test-logins.md`. Sie enthält die lokalen Einstiege für Akquisiteur,
Charity-Admin, Finanz-Lesezugriff, System-Admin und die öffentliche Persona,
aber bewusst keine kurzlebigen Codes oder Magic Links. Die Datei besitzt
Modus `0600` und wird nie committed.

### Minute 18–30: Kernweg und vollständigen Nachweis ausführen

Im sichtbaren Smoke:

1. mit `anna.akquise@leonaid.invalid` einen Code anfordern;
2. den neuesten Code unter `/mail/` lesen und einmalig bestätigen;
3. in „Meine Sponsoren“ die persönliche Krapfentaxi-Pipeline öffnen;
4. öffentlich unter `/krapfentaxi` eine Testbestellung erfassen.

Der reproduzierbare vollständige Abnahmelauf ist:

```sh
./leonaid test-golden-journey
```

Er startet ein isoliertes Projekt aus leeren Volumes, bedient sämtliche
Personas in drei Browserengines, prüft Twenty/PostgreSQL/RustFS/Mail/Typst und
wiederholt die Journey nach einem Golden Reset. Je nach bereits vorhandenem
Imagecache dauert er ungefähr fünf bis zehn Minuten. Der normale lokale Stack
bleibt davon unberührt.

### Wiederanlauf und Diagnose

```sh
./leonaid snapshot
./leonaid reset
./leonaid doctor
```

`reset` löscht ausschließlich ein explizit freigegebenes lokales LeonAid-
Compose-Projekt und stellt Core-PostgreSQL, Twenty, RustFS und Mailpit auf
Golden Data v1 wieder her. Alle Fach- und Betriebsbefehle zeigt
`./leonaid help`.

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
- [Implementierte Architektur](specs/leonaid-poc/ARCHITECTURE.md) —
  Laufzeitbild, Datenhoheit, API- und Sicherheitsgrenzen.
- [Development Guide](specs/leonaid-poc/DEVELOPMENT.md) — Docker-Workflow,
  Editor, Debugging und Fehlerdiagnose.
- [Betriebs- und Benutzer-Runbooks](specs/leonaid-poc/RUNBOOKS.md) —
  Normalbetrieb, Benutzerzugang und Incident-Ablauf.
- [Bekannte PoC-Grenzen](specs/leonaid-poc/KNOWN-LIMITS.md) — bewusst
  verschobener Scope und Produktivfreigabe-Blocker.
- [Abnahmeprotokoll](specs/leonaid-poc/ACCEPTANCE.md) — Commit, Locks,
  Dataset, Nachweise und ausstehende Sign-offs.

## Eckdaten der Lösung (Kurzfassung)

|                         |                                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------------------- |
| **Backend**             | [Twenty CRM](https://github.com/twentyhq/twenty) (Open Source, AGPL-3.0), self-hosted             |
| **Operatives Frontend** | React/TypeScript-PWA, shadcn/ui, freie Hugeicons; gemeinsame App Shell                            |
| **LeonAid Core**        | Python 3.13, FastAPI, frameworkfreie Application Services und transaktionaler Outbox-Worker       |
| **Feature-Rollout**     | OpenFeature für Python und React; im PoC providerneutral aus LeonAid PostgreSQL                   |
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

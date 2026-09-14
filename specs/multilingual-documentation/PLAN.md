# LeonAid: mehrsprachige Dokumentation

Stand: 14.09.2026. Status: in Umsetzung; DOC-010 und DOC-020 abgeschlossen.
Planungsbasis: Checkout `5074/leonaid`, Commit `2043b72b7c5453b37978f2a58436243dbc378a00`.

## 1. Ziel und Entscheidungsrahmen

LeonAid erhält eine eigenständige Dokumentationswebsite auf Deutsch und Englisch. Sie unterstützt Endanwender bei ihrer täglichen Arbeit sowie Sysadmins und Entwickler bei Installation, Betrieb und Weiterentwicklung. Inhalte werden zunächst im bestehenden Monorepo gepflegt und über CI geprüft, gebaut und später auf einer getrennten Website veröffentlicht.

Diese Spezifikation definiert Zielbild, Inhaltsstruktur, Pflegevertrag und abhakbare Umsetzungsschritte. Sie richtet noch keine Website, CI-Automation oder Veröffentlichung ein. Die Spezifikation selbst bleibt auf Deutsch; die DE/EN-Pflicht gilt für die späteren veröffentlichten Inhalte und die Website-Navigation.

### 1.1 Anforderungen und vorgeschlagene Entscheidungen

| ID | Anforderung / Planungsentscheidung | Einordnung |
| --- | --- | --- |
| DOC-R01 | Deutsch und Englisch ab dem ersten veröffentlichten Umfang; weitere Sprachen später ergänzbar | Nutzeranforderung |
| DOC-R02 | Getrennte Einstiege für Endanwender und technische Zielgruppen; Installation, Betrieb und Entwicklung abdecken | Nutzeranforderung |
| DOC-R03 | Diátaxis für Endanwender; auch für Betrieb und Entwicklung einsetzen | Nutzeranforderung / Empfehlung für technische Bereiche |
| DOC-R04 | Separate statische Website mit Astro und Starlight unter `apps/docs` | Empfohlene Konkretisierung der gewünschten Richtung |
| DOC-R05 | Inhalte und Site zunächst im Monorepo, gemeinsam mit Produktänderungen reviewen | Empfohlener Start entsprechend Nutzerpräferenz |
| DOC-R06 | PR-Prüfung und nächtlicher Build mit Veröffentlichung nach erfolgreichen Gates; manueller Wiederanlauf | Empfohlene Konkretisierung des CI-Vorschlags |
| DOC-R07 | Reproduzierbare Referenzgenerierung, geprüfte Übersetzungen, nachvollziehbarer Produktstand | Qualitätsanforderung dieses Plans |
| DOC-R08 | Root-README auf Englisch reduzieren und zunächst auf tatsächlich vorhandene Docs-Quelldateien im Repository verlinken; Website-URL und typische Repository-Informationen später ergänzen | Nutzeranforderung |

Erfolg bedeutet: Eine deutsch- oder englischsprachige Person findet ihren Einstieg, kann den beschriebenen Kernablauf anhand der Dokumentation durchführen und erkennt den dazugehörigen Produktstand sowie bekannte Grenzen.

### 1.2 Nicht im ersten Umfang

- Eigenes Dokumentationsrepository, Übersetzungsplattform oder Redaktions-CMS.
- Automatische Veröffentlichung ungeprüfter KI-Texte oder Übersetzungen.
- Vollständige öffentliche Abbildung aller Specs, Proofs und internen Runbooks.
- Interaktive API-Aufrufe gegen eine produktive Installation.
- Mehrere historische Dokumentationsversionen, PDF-Handbücher oder In-App-Hilfesystem.
- Neue Produktfunktionen, allgemeine Produktionsreife oder eine Lizenzentscheidung für LeonAid.

## 2. Verifizierter Ausgangspunkt und Migrationsbedarf

Die folgende Bestandsaufnahme beruht auf gelesenen Dateien, nicht auf neuen Laufzeitnachweisen. Vor dem Schreiben von Bedien- und Betriebsanleitungen muss der dann aktuelle Stand praktisch geprüft werden.

**Verbindliche Wahrheitsquelle:** Der implementierte Code ist immer maßgeblich.
Ausführbare Tests und reale Laufzeitnachweise zeigen, ob der relevante Codepfad
funktioniert. Specs, READMEs, frühere Proofs und dieses Inventar liefern
Absicht, Kontext und Fundstellen, dürfen dem aktuellen Code aber nicht
widersprechen oder ihn überstimmen. Bei einer Abweichung wird die
Dokumentation an den Code angepasst. Soll stattdessen das Produktverhalten
geändert werden, ist das eine eigene Implementierungsänderung mit eigenem
Nachweis; die Dokumentation nimmt sie nicht vorweg.

| Quelle | Befund | Konsequenz |
| --- | --- | --- |
| [Root-README](../../README.md) | Deutscher Einstieg, Golden Journey, verstreute Dokumentlinks; teilweise historische PoC-Formulierungen | Auf einen kurzen englischen GitHub-Einstieg reduzieren; ausführliche Anleitungen in die Docs übertragen und deren vorhandene Quelldateien verlinken |
| [Personas](../../PERSONAS.md) | Zentrale Rollen- und Produktreferenz mit Pflegevertrag | Grundlage für Anwenderzielgruppen; Rollenbeschreibungen nicht unabhängig neu erfinden |
| [Development Guide](../leonaid-poc/DEVELOPMENT.md), [Architektur](../leonaid-poc/ARCHITECTURE.md), [Runbooks](../leonaid-poc/RUNBOOKS.md) | Technische Dokumentation innerhalb einer Milestone-Spezifikation | Aktuelle Teile fachlich prüfen, in Diátaxis aufteilen und zuordnen |
| [Bekannte PoC-Grenzen](../leonaid-poc/KNOWN-LIMITS.md) | Datierter Stand vom Juli, unter anderem ohne CMS | Nicht als heutige Funktionsliste übernehmen; neuere [EmDash-Spezifikation](../emdash-campaign-microsite-spike/PLAN.md) und Implementierung abgleichen |
| [Lieferplanung](../krapfentaxi-lieferplanung/PLAN.md) | Neuere Erweiterung für Krapfentaxi-Bestellungen und mehrere Oberflächen | Aktuelle Bestellwege anhand ihrer eigenen Nachweise und UI prüfen |
| [Compose-README](../../infra/compose/README.md), [Pilot](../../infra/pilot/README.md), [Backup](../../infra/backup/README.md), [Upgrade](../../infra/upgrade/README.md) | Verteilte Betriebsanleitungen | Nach Installation, Tagesbetrieb, Diagnose, Wiederherstellung und Upgrade ordnen |
| [CLI](../../leonaid) | Kanonischer Einstieg einschließlich `test-handoff` und `generate-api-client`; noch keine Docs-Befehle | Docker-basierten Workflow erweitern, vorhandene Nachweise wiederverwenden |
| [Workspace](../../package.json), [Locks](../../bun.lock), [Campaign-App](../../apps/campaign-site/package.json) | Bun-Workspace `apps/*` / `packages/*`, Astro bereits vorhanden | Docs als separates Workspace-Paket; Starlight-Kompatibilität vor Versionswahl prüfen |
| [OpenAPI](../../packages/api-client/openapi.json), [API-CI](../../.github/workflows/api-contract.yml) | Generierter Vertrag mit bestehender Prüfung | Referenz daraus ableiten, keinen zweiten API-Vertrag pflegen |
| [CI](../../.github/workflows/ci.yml) | GitHub Actions, Docker-Toolchains und SHA-gepinnte Actions | Bestehende Konventionen für Docs verwenden |

Konkretes Drift-Beispiel: Das Root-README führt HTTP-Einstiege auf, während das Compose-README HTTPS als regulären Mitgliederzugang beschreibt. Die Migration klärt den tatsächlichen unterstützten Einstieg, statt beide Angaben ungeprüft zu kopieren. Auch historische Aussagen zu Rollen, Pilotstatus und CMS werden nicht allein aus dem Alter oder Namen einer Datei abgeleitet.

## 3. Informationsarchitektur nach Diátaxis

Diátaxis unterscheidet Tutorials zum Lernen, How-to-Anleitungen für konkrete Aufgaben, Referenz zum Nachschlagen und Erklärungen zum Verstehen. Das ist auch für technische Dokumentation geeignet. Die Trennung beschreibt den Zweck einer Seite, nicht vier verpflichtende Kapitel innerhalb jeder Seite. Quelle: [Diátaxis](https://diataxis.fr/).

Die Website beginnt mit drei verständlichen Einstiegen. „Technische Dokumentation“ umfasst dabei die beiden Bereiche Betrieb und Entwicklung; ein zusätzlicher Navigationsschritt ist nicht notwendig.

| Einstieg DE / EN | Zielgruppen | Tutorials / Lernen | How-to / Aufgaben erledigen | Reference / Nachschlagen | Explanation / Verstehen |
| --- | --- | --- | --- | --- | --- |
| Anwendung / Using LeonAid | Charity-Admin, Akquisiteur, Finanzrolle, öffentliche Besteller | Erste Kundenbestellung in einer Demo erfassen | Lieferfenster pflegen; Rechnung bearbeiten; Zugang wiedererlangen | Rollen, Felder, Bestell- und Rechnungsstatus | Aktion, CRM-Kontakt und Bestellung; Rechte innerhalb einer Aktion |
| Betrieb / Operating LeonAid | Installierende und Sysadmins | Lokale Demo installieren und prüfen | Pilot bereitstellen; sichern und wiederherstellen; Upgrade und Rückweg; Störung eingrenzen | Voraussetzungen, Konfiguration, Dienste, Ports und Operatorbefehle | Systemgrenzen, Persistenz, Mail, TLS und Betriebsmodell |
| Entwicklung / Developing LeonAid | Mitwirkende, Integrationsentwickler | Checkout bis zu einer kleinen Änderung mit passendem Test | API-Vertrag aktualisieren; debuggen; Migration ergänzen | API, Paketstruktur und Entwicklungsbefehle | Core, Adapter, Datenhoheit und gemeinsame Frontend-Bausteine |

Die Tabelle ist ein Inhaltsauftrag, keine Behauptung, dass jeder genannte Ablauf bereits produktiv freigegeben ist. DOC-010 prüft die Verfügbarkeit; nicht verfügbare Abläufe werden als Grenze beschrieben oder ausdrücklich zurückgestellt.

### 3.1 Seiten- und Navigationsregeln

- Sprachwahl und Zielgruppeneinstiege sind auf Desktop und Mobilgeräten erreichbar.
- Innerhalb eines Bereichs führen aufgabenorientierte Titel zu vier Diátaxis-Gruppen: „Lernen“, „Anleitungen“, „Referenz“, „Hintergründe“ beziehungsweise „Tutorials“, „How-to guides“, „Reference“, „Explanation“.
- Ein Tutorial führt durch einen reproduzierbaren Lernweg mit synthetischen Daten, Voraussetzungen, erwarteten Ergebnissen und sicherem Abschluss.
- Eine How-to-Seite nennt Ziel, benötigte Rolle, Voraussetzungen, Schritte, Erfolgskontrolle und relevante Fehlerbehebung. Destruktive Schritte erklären Auswirkung und Wiederherstellung am Ort der Handlung.
- Referenzseiten sind präzise und systematisch; Erklärungen begründen Zusammenhänge ohne einen Arbeitsablauf zu überladen.
- Rollen sind Filter- oder Orientierungshinweise innerhalb des Anwenderbereichs, keine getrennten Kopien derselben Anleitung. Öffentliche Besteller erhalten kurze, direkt verlinkbare Hilfen ohne vorausgesetzten Login.
- System-Admin in der Benutzerverwaltung und Sysadmin beim Serverbetrieb werden sprachlich unterschieden.
- Gemeinsame Begriffe und Fakten werden verlinkt. Getrennte Tutorials dürfen unterschiedliche Lernwege für dieselbe Funktion beschreiben.

### 3.2 Verbindlicher erster Inhaltsumfang

Vor dem ersten öffentlichen Start müssen folgende Einheiten auf DE und EN vollständig geprüft vorliegen:

| ID | Bereich | Mindestumfang und Nachweis |
| --- | --- | --- |
| CONTENT-01 | Orientierung | Startseite, drei Bereichseinstiege, Glossar und aktuelle Grenzen; Links führen zum passenden Produktstand |
| CONTENT-02 | Anwendung: Tutorial | Akquise-Persona meldet sich in der Demo an, wählt einen zugeordneten Kunden und erfasst eine Bestellung einschließlich Lieferangaben; UI-Schritte und Ergebnis stimmen |
| CONTENT-03 | Anwendung: How-to | Charity-Admin pflegt Lieferfenster; öffentliche Person bestellt; Finanzrolle bearbeitet einen belegten Rechnungs-/Zahlungsablauf; jeweils Voraussetzungen und Rechte erklärt |
| CONTENT-04 | Anwendung: Referenz/Erklärung | Rollen- und Statusreferenz sowie Erklärung Aktion/Kontakt/Bestellung; Aussagen gegen `PERSONAS.md`, Core und UI abgeglichen |
| CONTENT-05 | Betrieb: Tutorial/How-to | Frischer lokaler Demo-Start, klar getrennter Pilot-Installationspfad mit noch benötigten Betreiberangaben, Backup/Restore, Upgrade/Rollback und Login-/Mail-/TLS-Diagnose |
| CONTENT-06 | Betrieb: Referenz/Erklärung | Konfiguration mit sicheren Platzhaltern, Voraussetzungen, Dienste/Persistenz und Betriebsgrenzen; kein Demo-Reset als Produktionsanleitung |
| CONTENT-07 | Entwicklung: Tutorial/How-to | Kleine Änderung im frischen Checkout bis zum passenden Test sowie API-Vertrag regenerieren und Drift prüfen |
| CONTENT-08 | Entwicklung: Referenz/Erklärung | Versionierte API-Referenz, Befehls-/Paketübersicht und Architektur/Datenhoheit |

Für jede Einheit wird in DOC-010 eine endliche Liste von Seiten-IDs festgelegt. Keine automatische Vollabdeckung aller Produktbereiche: etwaige Survey- oder weiterführende CMS-Handbücher werden nach Bestandsaufnahme priorisiert. Fehlende Funktionen dürfen den ersten Umfang nur durch eine dokumentierte Scope-Entscheidung verändern, nicht durch leere Seiten mit dem Status „fertig“.

## 4. Mehrsprachigkeit und Pflegevertrag

### 4.1 URLs und Nutzererlebnis

Empfehlung: Deutsch als initiale redaktionelle Ausgangssprache und Starlight-Default; beide Sprachen besitzen explizite Präfixe `/de/` und `/en/`. `/` führt nachvollziehbar zum deutschen Einstieg und bietet die Sprachwahl. Weitere Sprachen benötigen ein eigenes Locale-Verzeichnis und vollständige Navigation.

Strukturbeispiele: `/de/user/how-to/manage-delivery-windows/` und `/en/user/how-to/manage-delivery-windows/`. Identische technische Slugs verbinden Übersetzungen; sichtbare Titel und Navigation sind übersetzt. Sprachwechsel erhält die aktuelle Seite. Interne Links bleiben in der gewählten Sprache, außer ein ausdrücklich gekennzeichneter Querverweis verlangt etwas anderes.

Starlight unterstützt Locale-Verzeichnisse, Seitenzuordnung über gleiche Dateinamen und gekennzeichneten Fallback auf die Standardsprache. Wir verwenden diese Basis; der erste DE/EN-Umfang muss jedoch ohne Fallback vollständig sein. Quelle: [Starlight i18n](https://starlight.astro.build/guides/i18n/).

### 4.2 Inhalt und Übersetzungsstand

- Code, API-Feldnamen, CLI-Befehle und tatsächliche UI-Labels werden nicht erfunden oder übersetzt, wenn das Produkt sie nur in einer Sprache anbietet. Eine englische Anleitung darf den deutschen Buttontext erklären.
- Ein gemeinsames DE/EN-Glossar regelt unter anderem Charity-Aktion, Akquisiteur, Sponsor, Bestellung und Rechnung; neue Begriffe werden im selben PR ergänzt.
- Screenshots stammen aus synthetischen Daten und tragen passende Sprache, Alternativtext und Produktstand. Produktdaten, Login-Codes und Sessions dürfen weder im Bild noch in Metadaten erscheinen.
- Vorschlag für zusätzliche, zu validierende Frontmatter-Felder: `docId`, `audience` (`user|ops|dev`), `diataxis` (`tutorial|how-to|reference|explanation`), `contentRevision`, `reviewedRevision` und `verifiedAgainst`. Standardfelder wie Titel und Beschreibung bleiben erhalten. Locale wird aus dem Pfad abgeleitet.
- `docId` ist für das Sprachpaar gleich und innerhalb einer Sprache eindeutig. `contentRevision` bezeichnet die fachliche Revision der deutschen Quelle; `reviewedRevision` der englischen Seite muss ihr entsprechen. `verifiedAgainst` benennt den geprüften Produkt-Commit oder Release. Redaktionelle Revision und Softwareversion sind unterschiedliche Angaben.
- Inhaltliche Quelländerungen erhöhen die Revision. Reine Formatkorrekturen benötigen das nicht; die PR-Review prüft diese Unterscheidung. CI erkennt fehlende Seiten und abweichende Revisionen, aber keine semantisch falsche Übersetzung.
- Für den veröffentlichten DE/EN-Umfang blockieren fehlende oder veraltete Übersetzungen den Docs-Release. Entwürfe sind von Routen, Sidebar, Sitemap und Suchindex ausgeschlossen. Geplante weitere Sprachen dürfen später mit sichtbarem Fallback starten.
- KI darf Entwürfe vorschlagen. Fachreview und Sprachreview bleiben Voraussetzung für den Merge; der Nachtlauf erzeugt keine neue Prosa.

### 4.3 Verantwortung und Definition of Done

Produktänderungen mit Einfluss auf Bedienung, API, Konfiguration oder Betrieb aktualisieren betroffene Docs im selben PR. Eine PR-Checkliste verlangt Docs-Links oder eine konkrete Begründung „keine Dokumentationsauswirkung“. Eine reine Pfadprüfung kann diese Verantwortung nicht ersetzen.

Bei jedem Review wird die beschriebene Strecke vom sichtbaren Einstieg bis zum
maßgeblichen Codepfad verfolgt. Historische Specs und Proofs gelten nie als
Ersatz für diesen Abgleich.

Fachreview: zuständige Produkt-/Codeverantwortliche. Sprachreview: Person mit ausreichender DE/EN-Kompetenz; anfangs kann dieselbe Person beide Aufgaben übernehmen. Betrieb und Freigabe der Docs-Site haben einen benannten Maintainer. Konkrete Personen werden bei DOC-010 eingetragen.

Eine Seite ist fertig, wenn Inhalt und Übersetzung geprüft sind, Produktstand und Rechte stimmen, der Ablauf beziehungsweise die Referenz validiert wurde und die Website-Gates bestehen. Ein monatlicher redaktioneller Drift-Check prüft insbesondere Betriebsanleitungen und bekannte Grenzen; dafür wird hier keine Automation eingerichtet.

## 5. Repository und technische Architektur

### 5.1 Monorepo zuerst

| Kriterium | Monorepo | Eigenes Repository |
| --- | --- | --- |
| Produkt- und Docs-Änderung | Ein PR und derselbe Commitstand | Synchronisation über mehrere PRs oder Releases |
| Generierte Referenz | Direkter Zugriff auf geprüfte lokale Quellen | Versionierte Übergabeartefakte erforderlich |
| Redaktionelle Zugriffsrechte | An Repository-Rechte gekoppelt | Eigenständige Rechte und Releaseprozesse möglich |
| Toolchain | Bestehende Locks und Docker-Konventionen | Eigene Installation und Wartung |
| Veröffentlichung | Separates Artefakt und Deployment trotzdem möglich | Ebenfalls separate Veröffentlichung |

**Empfehlung:** `apps/docs` im Monorepo. Das gewünschte getrennte Hosting erfordert kein getrenntes Repository. Eine spätere Auslagerung wird erst bei eigenständigem Redaktionsteam, anderen Zugriffsrechten oder unabhängigem Releasezyklus bewertet.

### 5.2 Vorgeschlagene Struktur

```text
apps/docs/
  package.json                 # @leonaid/docs
  astro.config.mjs
  src/content.config.ts        # Starlight-Schema plus Pflegefelder
  src/content/docs/
    de/{user,ops,dev}/          # darunter die vier Diátaxis-Typen
    en/{user,ops,dev}/          # identische relative Seitenpfade
  src/content/i18n/            # projektspezifische UI-Übersetzungen
  public/                     # ausschließlich freigegebene Docs-Assets
  scripts/                    # kleine Docs-spezifische Prüf-/Generierwerkzeuge
  README.md                   # Autorenworkflow und Generierungsvertrag
  dist/                       # ignoriertes, erzeugtes Veröffentlichungsartefakt
specs/multilingual-documentation/
  PLAN.md                     # diese Spezifikation, keine Website-Eingabe
  CONTENT-INVENTORY.md         # später: Quellen, Zielseiten und Reviewstatus
  PROGRESS.md                  # später: tatsächlicher Umsetzungsstand
  proofs/DOC-NNN.md            # später: taskbezogene Nachweise
.github/workflows/docs.yml     # später: Prüfung, Build und Veröffentlichung
```

Astro/Starlight rendert statisches HTML mit der integrierten Pagefind-Suche. Das Deployment benötigt keine LeonAid-Datenbank, keine Core-Session und kein EmDash. Die Suche wird am Produktionsbuild geprüft, nicht nur am Dev-Server. Quelle: [Starlight Site Search](https://starlight.astro.build/guides/site-search/).

Die Docs-App importiert keine laufenden Produkt-UIs und keine vertraulichen Specs. Fachinformationen werden gezielt übertragen; Referenzquellen sind explizit freigegeben. MDX nur dort einsetzen, wo Markdown nicht genügt. Keine eigene Suchplattform oder umfassenden Theme-Overrides im ersten Schritt.

Starlight-Version und Astro-Kompatibilität werden im bestehenden Bun-Workspace geprüft und gelockt. Ein Versionskonflikt darf keine ungeplanten Upgrades der Produkt-Apps auslösen. Docs-Preview und Build laufen über digest-gepinnte Docker-Toolchains und den Wrapper `./leonaid`; ein statischer Docs-Build startet nicht den vollständigen Produktstack.

### 5.3 Quellen, Generierung und spätere Auslagerbarkeit

- **Redaktionell:** Tutorials, How-tos, Erklärungen, Rollenbeschreibungen und geprüfte Übersetzungen liegen versioniert in `apps/docs`.
- **Generiert:** Die API-Referenz verwendet den geprüften OpenAPI-Vertrag. API-Bezeichner bleiben sprachneutral, Einordnung und Navigation DE/EN. Vollständig automatisierte Übersetzung von Schema-Beschreibungen ist nicht vorgesehen; englische/deutsche Erläuterungen werden kuratiert oder sprachlich gekennzeichnet.
- **Weitere Referenz:** CLI- und Konfigurationsreferenz zunächst aus explizit geprüften Quellen pflegen. Generierung nur, wenn ein stabiler, geheimnisfreier maschinenlesbarer Eingang existiert; keine ungeprüfte Auswertung beliebiger Laufzeitkonfiguration.
- Generatoren schreiben nur in definierte erzeugte Docs-Verzeichnisse innerhalb des Build-Workspace, nie über handgeschriebene Seiten. Ausgabe bleibt uncommitted, wird reproduzierbar gebaut und folgt den gleichen Publikations- und Sprachprüfungen.
- Der bestehende API-Vertragscheck verhindert Drift zwischen Core und eingechecktem OpenAPI. Generierte Dokumentation besitzt keinen zweiten Vertragsstand und zieht keine aktuelle Fremd-API aus dem Netz.
- Nach der Inhaltsmigration gibt es genau eine gepflegte Anleitung pro Zweck und Sprache. Bestehende Einstiegspunkte erhalten Links zur kanonischen Seite. Historische Specs und Abnahmen bleiben historische Dokumente; sie werden nicht nachträglich in aktuelle Handbücher umgeschrieben.
- Eine spätere Auslagerung übernimmt `apps/docs` und einen versionierten Satz freigegebener Referenzartefakte samt Quell-SHA. Stabile öffentliche URLs bleiben erhalten. Kein automatischer Spiegel und keine Submodule auf Vorrat.

### 5.4 Root-README als kompakter GitHub-Einstieg

Das Root-`README.md` wird bei der Inhaltsmigration deutlich gekürzt und vollständig auf Englisch verfasst. Es enthält zunächst eine kurze Projektbeschreibung und einen übersichtlichen Dokumentationseinstieg für Anwendung, Betrieb und Entwicklung mit Links zu Deutsch und Englisch. Ausführliche Installationsschritte, Golden-Journey-Anleitungen, Architekturübersichten und Runbooks werden nach geprüfter Übernahme in die Docs nicht nochmals im README gepflegt.

Die Dokumentationslinks verweisen zunächst über relative Repository-Pfade direkt auf die tatsächlich erstellten und versionierten Markdown-/MDX-Quelldateien unter `apps/docs/src/content/docs/` (Rohformat, auf GitHub einsehbar). Sie führen weder auf geplante, noch nicht vorhandene Dateien noch auf lokale Buildausgaben unter `dist`. Sprach- und Bereichseinstiege müssen deshalb als versionierte Quelldateien vorliegen und auch ohne laufende Dokumentationswebsite verständlich sein. Eine nur während des Builds erzeugte Referenz wird über ihre vorhandene redaktionelle Einstiegsdatei erschlossen.

Die tatsächliche URL der Dokumentationswebsite wird erst nach deren Veröffentlichung zusätzlich aufgenommen; die Repository-Links bleiben als direkter Zugang zu den Quellen erhalten. Typische weitere Repository-Informationen werden in einem späteren Schritt ergänzt. Dieser Plan erweitert das README nicht vorsorglich um zusätzliche Standardabschnitte. Bereits notwendige Status- und Lizenzhinweise bleiben knapp und korrekt erhalten.

Abnahmeregel: README-Inhalte erst entfernen, wenn die entsprechenden Docs vorhanden und geprüft sind. Alle README-Dokumentationslinks müssen im selben Commit auf vorhandene Dateien zeigen. Die englische README-Sprache ist unabhängig von der deutschen redaktionellen Ausgangssprache der zweisprachigen Dokumentation.

## 6. Build, Veröffentlichung und Betriebsvertrag

### 6.1 Was „nachts neu erzeugen“ bedeutet

CI rendert versionierte, bereits geprüfte Inhalte, generiert freigegebene Referenzen und aktualisiert den Suchindex. Ein Builddatum beweist keine fachliche Aktualität. Sichtbar werden der dokumentierte Produktstand und das letzte Inhaltsreview; der Build führt zusätzlich ein Manifest mit Quell-SHA, Dokumentationsstand und Artefakt-ID.

Empfohlener Erstmodus: Die Website dokumentiert den aktuellen Entwicklungsstand des Default-Branches und kennzeichnet diesen ausdrücklich als Entwicklungs-/Pilotdokumentation. Ein nächtlicher Build von `main` darf nicht als Handbuch eines stabilen Releases erscheinen. Sobald ein verbindlicher Releasekanal feststeht, wird die öffentliche Standarddokumentation an dessen Produktrevision gebunden; eine getrennte Development-Version ist dann eine eigene Folgeentscheidung.

### 6.2 CI-Ereignisse

| Ereignis | Verhalten |
| --- | --- |
| Pull Request | Metadaten/Sprachvollständigkeit, Links/Anker, Referenzgenerierung, statischer Build und Browser-Smoke; herunterladbares Preview-Artefakt ohne Deployment-Secrets |
| Push auf Default-Branch | Gleiche Docs-Gates und Artefakt; anfangs keine sofortige öffentliche Veröffentlichung |
| Nächtlich | Default-Branch-SHA fixieren, alle Docs-Gates ausführen, geprüftes Artefakt veröffentlichen |
| Manuell | Denselben Ablauf vom geschützten Default-Branch erneut starten, etwa nach ausgefallenem Nachtlauf |

Zeitvorschlag: täglich 02:23 UTC, entsprechend 03:23 Uhr im deutschen Winter und 04:23 Uhr im Sommer. Keine minutengenaue Zusage: GitHub beschreibt mögliche Verzögerungen/ausfallende Schedule-Jobs und die Bindung an den Default-Branch. Bei öffentlichen Repositories ist außerdem die Deaktivierung nach 60 Tagen ohne Aktivität zu berücksichtigen. Quelle: [GitHub Actions Schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

PR-/Push-Prüfung berücksichtigt neben `apps/docs/**` auch referenzierte Quellen, `PERSONAS.md`, API-Schema, Generatoren, Locks, Toolchain und Docs-Workflow. Der Nachtlauf hat keinen Pfadfilter. Während des Aufbaus ist eine ungefilterte Docs-Prüfung die einfachere sichere Vorgabe. Eine erforderliche Statusprüfung darf bei späteren Pfadfiltern nicht dauerhaft „pending“ bleiben.

### 6.3 Deployment und Fehlerverhalten

1. Build und Prüfung erfolgen ohne Produktionszugang mit read-only Repository-Rechten; Actions werden analog zum Repo per SHA gepinnt.
2. Ein separater Deployment-Job erhält ausschließlich die Rechte für das Docs-Ziel, bevorzugt kurzlebig, sofern der gewählte Hoster dies unterstützt. Keine Secrets oder schreibenden Deployments aus untrusted PR-Code.
3. Nur `apps/docs/dist` und das bereinigte Buildmanifest werden übertragen. Kein Repository-Root, `.env`, `.local`, Source-Map-Dump oder interner Proof-Ordner.
4. Das neue Artefakt wird atomar aktiviert. Deployment-Läufe werden serialisiert; eine ältere Revision darf eine bereits veröffentlichte neuere Revision nicht überschreiben.
5. Ein HTTPS-Smoke prüft DE/EN-Einstiege, eine konkrete Seite je Bereich, Sprachwechsel, Assets, Suchergebnis und ausgelieferte Manifest-SHA.
6. Bei Build-/Übersetzungs-/Linkfehlern bleibt die letzte gute Website aktiv. Bei fehlgeschlagenem Live-Smoke wird das vorige bekannte gute Artefakt wieder aktiviert und erneut geprüft.
7. Fehler und ein überfälliger erfolgreicher Nachtlauf werden dem benannten Maintainer sichtbar gemacht. Vorschlag: Alarm nach 36 Stunden ohne erfolgreichen Lauf; Monitoring muss unabhängig vom Schedule laufen, damit auch ausgefallene Trigger erkannt werden. Umsetzung passend zum späteren Hosting.

Hoster, Domain und Zugang sind noch offen. Der Build muss vor deren Auswahl lokal und als CI-Artefakt abnehmbar sein; öffentliches Deployment bleibt ein getrenntes Gate. Erst beim öffentlichen Start sind domainabhängige Canonicals, Sprachalternativen, Sitemap und die für die Website geltenden Anbieter-/Datenschutzhinweise final zu prüfen. Der vorhandene Lizenzstatus wird korrekt wiedergegeben; die Docs erklären LeonAid nicht stillschweigend zu Open Source.

## 7. Abhakbare Umsetzung und Abnahme

Alle Tasks bleiben bis zur tatsächlichen Umsetzung und ihrem Nachweis offen. `PROGRESS.md` dokumentiert später Stand und Blocker, `proofs/DOC-NNN.md` jeweils Quell-SHA, geprüfte Seiten, ausgeführte Befehle, Ergebnis und bereinigte Artefakte. Ein grüner Site-Build ersetzt keine fachliche oder öffentliche Abnahme.

Die folgenden Docs-Befehle sind **neu einzuführende Zielverträge**, heute nicht vorhanden: `./leonaid docs-dev`, `./leonaid docs-check`, `./leonaid docs-build`, `./leonaid docs-preview`, `./leonaid test-docs`. Sie erhalten Hilfeausgabe und Docker-Ausführung. `docs-check` prüft Inhalt/Sprachen/Quellen, `docs-build` erzeugt `dist`, `docs-preview` serviert genau diesen Build und `test-docs` prüft ihn im realen Browser.

### DOC-010 – Bestand, Umfang und Pflegeverantwortung

Abhängigkeit: keine.

- [x] `CONTENT-INVENTORY.md` mit jeder Startumfang-Seite, Quellpfaden, Ziel-URL, Diátaxis-Typ, Zielgruppe, DE/EN-Status und Reviewer anlegen.
- [x] Historische Aussagen zu Pilot, CMS, Rollen und Lieferangaben gegen aktuellen Code und vorhandene Nachweise abgleichen; Abweichungen einzeln dokumentieren.
- [x] CONTENT-01 bis CONTENT-08 auf konkrete Seiten abbilden und Verantwortliche benennen; Zurückstellungen begründen.
- [x] Entwicklungsstand als ersten Publikationskanal sowie Monorepo-/Locale-Entscheidung festhalten.

Nachweis: Keine Startumfang-Seite ohne Quelle, Abnahmeschritt oder Reviewzuständigkeit; Rollen mit `PERSONAS.md` abgeglichen. Ungeklärte Funktionsverfügbarkeit stoppt die betroffene Anleitung, nicht die restliche Bestandsaufnahme.

### DOC-020 – Starlight-Grundgerüst und Toolchain

Abhängigkeit: DOC-010.

- [x] `@leonaid/docs` mit gelockter kompatibler Astro-/Starlight-Kombination und Docker-Wrapperbefehlen einführen.
- [x] DE/EN-Routing, drei Zielgruppeneinstiege, Diátaxis-Navigation und Pagefind konfigurieren.
- [x] `dist` und temporäre Generatorausgaben ignorieren; minimale Beispielseiten zum Nachweis verwenden.
- [x] Frontmatter-Schema und vollständigen Ausschluss von Entwürfen umsetzen.

Nachweis: Frischer Checkout baut und previewt die Site ohne Produktstack oder Produkt-Secrets. Desktop/Mobil und Tastatur zeigen beide Sprachen. Vorhandene Produkt-Apps werden bei gemeinsam geänderten Locks/Toolchains mit den betroffenen bestehenden Checks geprüft. Versionskonflikte werden gelöst, bevor Inhalte auf dem Gerüst aufbauen.

### DOC-030 – Redaktion, Übersetzungen und Qualitätsgates

Abhängigkeit: DOC-020.

- [ ] Vier kurze Autorenvorlagen, Glossar und Pflegevertrag dokumentieren.
- [ ] Prüfung auf eindeutige Seiten-IDs, gültige Metadaten, DE/EN-Parität und veraltete Übersetzungsrevisionen einführen.
- [ ] Interne Routen/Anker, Assets und locale-treue Links am Build prüfen; externe Links im Nachtlauf mit begrenzten Retries kontrollieren und temporäre Netzfehler getrennt melden.
- [ ] PR-Checkliste für Dokumentationsauswirkung und Reviews ergänzen.

Nachweis: Bewusst fehlende Übersetzung, veraltete Revision und defekter interner Anker lassen `docs-check` scheitern. Nach Korrektur besteht der Check. Ein Entwurf taucht weder über direkten URL-Aufruf noch in Suche/Sitemap auf. Ein fachlich falscher Text wird durch Review behandelt, nicht als automatisch erkannt behauptet.

### DOC-040 – Endanwenderdokumentation DE/EN

Abhängigkeit: DOC-030.

- [ ] CONTENT-01 bis CONTENT-04 aus geprüftem Bestand schreiben und übersetzen.
- [ ] Aktuelle Akquise-, Charity-Admin-, Finanz- und öffentliche Bestellwege mit synthetischen Daten nachvollziehen; tatsächliche UI-Labels verwenden.
- [ ] Mindestens ein Tutorial und die aufgelisteten How-tos in beiden Sprachen anhand der Anleitung durchlaufen; bestehende Journey-Tests als ergänzenden Nachweis verwenden.

Nachweis: Erwartete Ergebnisse treten ein, Rollen- und Aktionsgrenzen sind korrekt beschrieben, Screenshots enthalten ausschließlich freigegebene synthetische Daten. Abweichende UI-/Core-Funktionalität wird vor Veröffentlichung korrigiert oder die Anleitung nach belegtem Scope angepasst.

### DOC-050 – Betriebs- und Entwicklerdokumentation DE/EN

Abhängigkeit: DOC-030; kann nach DOC-040 oder unabhängig davon bearbeitet werden.

- [ ] CONTENT-05 bis CONTENT-08 erstellen; Demo, Pilotkonfiguration und produktive Betreiberverantwortung klar kennzeichnen.
- [ ] OpenAPI-Referenz aus dem bestehenden geprüften Vertrag reproduzierbar bauen; kuratierte Erklärung davon getrennt halten.
- [ ] Installations- und Entwicklungstutorial aus frischem Checkout durchführen; vorhandenen `test-handoff` auf Wiederverwendung prüfen.
- [ ] Restore und Upgrade/Rollback anhand der Anleitungen in isolierter synthetischer Umgebung durchspielen; vorhandene passende Betriebsnachweise wiederverwenden/gezielt ergänzen.
- [ ] Alte Einstiegspunkte zur neuen kanonischen Anleitung verlinken und historische Dokumente als solche erhalten.
- [ ] Root-README gemäß Abschnitt 5.4 auf einen kurzen englischen GitHub-Einstieg reduzieren und die tatsächlich vorhandenen DE/EN-Docs-Quelldateien für Anwendung, Betrieb und Entwicklung relativ verlinken; typische weitere Repository-Informationen bleiben einer späteren Ergänzung vorbehalten.

Nachweis: Keine fehlenden impliziten Installationsschritte; Erfolg, Fehlerdiagnose und Rückweg belegt. Zweimalige Referenzgenerierung aus identischen Eingaben liefert identische fachliche Inhalte. Fehlender oder vom Core abweichender API-Vertrag blockiert die Referenz. Synthetische Betriebsproben werden nicht als produktive Betreiberfreigabe ausgegeben. Das englische Root-README bleibt auf GitHub übersichtlich; alle Dokumentationslinks lösen auf vorhandene Quelldateien auf und sind ohne Site-Deployment nutzbar. Die README-Reduktion wartet bei Anwenderinhalten auf deren Abnahme in DOC-040.

### DOC-060 – CI und vollständiges Veröffentlichungsartefakt

Abhängigkeit: DOC-040 und DOC-050.

- [ ] PR, Push, Nachtlauf und manuellen Wiederanlauf mit denselben Docs-Gates einrichten; benötigte API-Vertragsprüfung integrieren.
- [ ] Manifest, übersetzte Navigation, Sprachwechsel, Suchindex, Linkprüfung und Browser-Smoke in beiden Sprachen nachweisen.
- [ ] Mindestens 375-px-Mobilansicht, Desktop, 200-%-Zoom, Tastaturbedienung und automatisierte Accessibility-Prüfung durchführen; kritische Befunde beheben.
- [ ] Veröffentlichtes Dateiset über Allowlist prüfen; absichtlich platzierte Testdatei außerhalb des Docs-Ausgabevertrags darf nicht im Artefakt landen.

Nachweis: Echter PR-CI-Lauf und manueller Lauf terminal grün; echtes Nacht-Ereignis separat nachgewiesen, sobald der Workflow auf dem Default-Branch liegt. Ein manueller Lauf beweist den Schedule nicht. Fehlerfälle verhindern Promotion. Alle ersten DE/EN-Seiten sind fachlich und sprachlich freigegeben. Ohne Hosting endet dieser Task bei einem geprüften Artefakt.

### DOC-070 – Getrenntes Hosting und öffentliche Abnahme

Abhängigkeit: DOC-060 sowie festgelegter Hoster, Domain, Deployment-Zugang und Veröffentlichungsrahmen.

- [ ] Statisches Ziel mit HTTPS, atomarer Promotion, minimalen Rechten und Rückweg konfigurieren.
- [ ] Website-Metadaten, Betreiberhinweise und öffentliche Inhaltsfreigabe abschließen.
- [ ] Tatsächliche Nachtveröffentlichung, Fehleralarm, Erkennung eines ausgebliebenen Laufs und Wiederanlauf prüfen.
- [ ] Live-Smoke auf der getrennten Website in DE/EN durchführen; Manifest-SHA gegen das freigegebene Artefakt prüfen.
- [ ] Nach erfolgreicher Veröffentlichung die tatsächliche Dokumentationswebsite-URL zusätzlich im englischen Root-README verlinken; bestehende Docs-Quelllinks erhalten.
- [ ] Fehlgeschlagenen Live-Smoke und Rückkehr zum vorherigen Artefakt kontrolliert nachweisen.

Nachweis: Beide Sprachen sind unter der gewählten Domain anonym erreichbar, Suche und Sprachwechsel funktionieren, die neue Revision wird ausgeliefert und der Rückweg ist belegt. Ohne diese Nachweise lautet der Status „lokal/CI abgenommen, Veröffentlichung offen“.

## 8. Gesamt-Abnahme und offene Entscheidungen

| Anforderung | Nachweisverantwortliche Tasks |
| --- | --- |
| DOC-R01 Mehrsprachigkeit | DOC-020, DOC-030, DOC-040, DOC-050, DOC-060, DOC-070 |
| DOC-R02 Zielgruppen | DOC-010, DOC-040, DOC-050 |
| DOC-R03 Diátaxis | DOC-010, DOC-030, DOC-040, DOC-050 |
| DOC-R04 Website | DOC-020, DOC-060, DOC-070 |
| DOC-R05 Monorepo | DOC-010, DOC-020, DOC-050 |
| DOC-R06 CI/Nachtlauf | DOC-060, DOC-070 |
| DOC-R07 Qualität/Produktstand | DOC-030 bis DOC-070 |
| DOC-R08 Kompaktes englisches Root-README | DOC-050, DOC-070 |

Für die technische Vorbereitung sind keine weiteren Nutzerangaben erforderlich. Die folgenden Entscheidungen werden erst vor dem jeweils abhängigen Schritt benötigt:

| Entscheidung | Vorgeschlagener Ausgangspunkt | Spätestens benötigt |
| --- | --- | --- |
| Redaktionelle Ausgangssprache | Deutsch; vollständiges Englisch für den Startumfang | DOC-010 |
| Öffentlich dokumentierter Produktstand | Klar markierter Default-Branch-Entwicklungs-/Pilotstand | DOC-010; vor Veröffentlichung erneut prüfen |
| Reviewer und Site-Maintainer | Bestehende Produkt-/Codeverantwortliche mit DE/EN-Review | DOC-010 |
| Domain und statischer Hoster | Getrennte Docs-Website; konkreten Anbieter später auswählen | DOC-070 |
| Deployment-Identität und Alarmempfänger | Minimaler Docs-Zugriff, benannter Maintainer | DOC-070 |
| Nutzungsrechte an Dokumentation und öffentliche Betreiberangaben | Vorhandenen Projektstatus respektieren, gesonderte Entscheidung falls nötig | DOC-070 |

Eine spätere Abnahme trennt Inhaltsvollständigkeit, lokale Funktion, CI und öffentliche Veröffentlichung ausdrücklich. Ein offener Hosting-Zugang verhindert weder die Inhaltsarbeit noch einen vollständigen reproduzierbaren Build.

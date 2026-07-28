# PILOT-012 – Rollen und Aktionsmitgliedschaften vollständig verwalten

Task-ID: `PILOT-012`

Nachweisdatum: 28. Juli 2026

Status: technisch vollständig bewiesen, formaler Abschluss blockiert

## Ergebnis

Die Rollenverwaltung ist als revisionsgesicherte FastAPI-/PostgreSQL-Funktion
und als geführter Bestandteil der Mitgliederverwaltung umgesetzt:

- System-Admins können globale Rollen und alle für eine Aktion verfügbaren
  Aktionsrollen zuweisen und entziehen.
- Charity-Admins sehen und verändern ausschließlich Aktionsrollen in selbst
  verwalteten Aktionen.
- Globale Rollen und fremde Aktionen bleiben für Charity-Admins auch bei
  direkten API-Aufrufen gesperrt.
- Der letzte aktive System-Admin sowie der letzte Charity-Admin einer
  operativ veränderbaren Aktion können nicht ersatzlos entfernt werden.
- Die Fahrerrolle wird nur bei vorhandener `delivery`-Capability angeboten;
  ein produktiver Lieferworkflow wird dadurch nicht vorgezogen.
- Erfolgreiche Änderungen wirken ohne erneute Anmeldung ab dem nächsten
  Request auf Navigation, Listen, Exporte und Dokumentzugriff.
- Ein Membership-Entzug setzt das Gültigkeitsende, löscht jedoch weder den
  historischen Datensatz noch vorhandene Akquisezuordnungen oder deren
  Verlauf.
- Fresh Login, erwartete Revision, Idempotenzbeleg und AuditEvent gehören zu
  jedem Änderungskommando.

OpenAPI und der generierte TypeScript-Client enthalten getrennte, typisierte
Endpunkte für globale und aktionsbezogene Rollenänderungen.

## Automatische Nachweise

```sh
./leonaid test-unit
./leonaid test-identity
/bin/sh tools/ci/lint-types.sh
```

Ergebnis:

```text
173 passed
identity-contract: Rollen, Statusrevision, Idempotenz, Konkurrenz,
Archivtreue und sofortiger Sitzungsentzug real bewiesen
10 passed in Chromium
identity-test: OK: Mitgliederübersicht, Rollen-Offboarding, Statusworkflow,
Konkurrenz, Sitzungsentzug und Persona-Navigation real bewiesen
ci-lint-types: OK
```

Der Identity-Integrationstest baut FastAPI und PostgreSQL aus leeren Volumes
auf und belegt insbesondere:

1. veraltetes Fresh Login wird abgewiesen;
2. ein Charity-Admin kann weder globale Rollen noch Rollen einer fremden
   Aktion ändern;
3. Zuweisung, idempotente Wiederholung und Entzug einer aktionsbezogenen
   Finanzrolle;
4. unmittelbaren Gewinn und Entzug von Rechnungsnavigation sowie echtem
   Rechnungs-/Dokumentzugriff in einer bereits bestehenden Sitzung;
5. unmittelbaren Gewinn und Entzug von Systemnavigation, vollständiger
   Mitgliederliste und realem Datenschutzexport durch eine globale
   System-Admin-Rolle;
6. die Capability-Grenze der Fahrerrolle und ihre Wirkung im nächsten
   Navigationsrequest;
7. unveränderte Membership-ID, `active_from`, Akquisezuordnungen und
   Zuordnungsverläufe nach dem Entzug;
8. Ablehnung des letzten Charity-Admin-Entzugs und erfolgreichen Entzug nach
   atomar vorbereiteter Nachfolge;
9. genau einen Gewinner zweier konkurrierender globaler Rollenänderungen;
10. genau einen PII-freien Audit- und Idempotenzbeleg je erfolgreichem
    Kommando und keine unbeabsichtigten Outbox-Nachrichten.

## Browsernachweise

Der automatisierte Chromium-Ablauf verwendet ausschließlich echte API-,
PostgreSQL- und Frontenddaten:

1. Charity-Admin sieht nur Rollen eigener Aktionen und keine globalen
   Steuerelemente.
2. Direkte verbotene API-Aufrufe auf globale und fremde Aktionsrollen enden
   mit `403`.
3. System-Admin weist über Bestätigungsdialoge eine globale Finanzrolle,
   aktionsbezogene Finanzrolle und Fahrerrolle zu.
4. Eine bereits geöffnete Zielsession erhält im nächsten Request Sponsor-,
   Finanz- und Fahrerberechtigungen.
5. Das responsive Web-Menü zeigt den neu verfügbaren Rechnungsbereich; der im
   Pilot absichtlich noch nicht implementierte Lieferbereich bleibt
   deaktiviert.
6. Vollständiges Offboarding entzieht alle Zusatzrollen und die
   Akquisiteurrolle; die nächste Anfrage zeigt nur noch den neutralen
   Überblick.
7. Axe meldet keine kritischen oder ernsten Befunde.

Die privaten Screenshots
`role-charity-scope.png`, `roles-assigned.png` und `roles-offboarded.png`
werden mit Dateimodus `0600` unter `.local/pilot/evidence/identity/` abgelegt
und nicht versioniert.

Der Workflow wurde zusätzlich sichtbar im In-App-Browser der kanonischen
Entwicklungsinstanz bedient. Dabei wurde einer bestehenden synthetischen
Persona die Finanzrolle für die aktive Krapfentaxi-Aktion zugewiesen. Der
abgelaufene Fresh-Login-Nachweis führte über eine reale Worker-/SMTP-/
Mailpit-Nachricht zum sechsstelligen Code. Nach einem Reload waren zwei
Aktionsrollen sichtbar. Anschließend wurde die Zusatzrolle wieder entzogen;
nach dem nächsten Request blieb ausschließlich die ursprüngliche
Akquisiteurrolle erhalten.

## Docker-Ressourcen

Der Test verwendet das exakte Compose-Projekt `leonaid-poc040-test`. Nach dem
erfolgreichen Lauf bestätigte die Inventur jeweils null Container, Netze und
Volumes mit diesem Projektlabel. Der kanonische sichtbare Entwicklungsstack
`leonaid` blieb aktiv und wurde anschließend mit den aktuellen Images neu
gebaut.

## Formale Taskgrenze

Alle Kriterien von `PILOT-012` sind technisch bewiesen. Der Task bleibt im
Plan formal offen, weil der Pilotvertrag einen abgeschlossenen Task mit
offenen Abhängigkeiten ablehnt: `PILOT-012` hängt von `PILOT-010` und
`PILOT-011` ab, die wegen ihrer noch offenen Vorbedingungen weiterhin formal
offen sind. Diese Abhängigkeit wird nicht durch einen verfrühten Haken
umgangen.

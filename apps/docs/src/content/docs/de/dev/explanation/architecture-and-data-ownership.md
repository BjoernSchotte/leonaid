---
title: Architektur und Datenhoheit
description: Die Core-, CRM-, Storage- und Frontend-Grenzen hinter LeonAids modularer Architektur.
docId: DOC-P037
audience: [dev]
diataxis: explanation
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: e2e199217b9b0d23fc0ad225051cfc36fe01daf5
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

Der FastAPI Core besitzt Authentifizierung, Autorisierung und sämtliche
Fachoperationen. Sein PostgreSQL speichert Identitäten, Aktionen,
Mitgliedschaften, Zuordnungen, Aktivitäten, Bestellungen, Rechnungen,
Zahlungen, Audit und Outbox. Policies werden dort bei jedem Request geprüft.

Twenty ist System of Record für Firmen und Personen. LeonAid speichert stabile
CRM-IDs und unveränderliche fachliche Snapshots, nicht eine zweite führende
Kontaktkopie. Request-Pfade fragen Twenty nur nach Name, Match-Schlüssel
oder expliziten Datensatz-IDs ab und listen nie eine ganze Sammlung: Core
speichert an jeder geschriebenen Firma und Person einen normalisierten
Match-Schlüssel in einem provisionierten Feld, findet Dubletten über eine
exakte Schlüsselabfrage, und ein idempotentes Reparaturkommando ergänzt
außerhalb von LeonAid angelegte Datensätze. Die einzige Ausnahme von „keine
Kontaktkopie“ ist der Suchindex `sponsor_search_entry`: Er hält Name und Ort
der Firmen und Personen mit Akquise-Zuordnung, damit die Suche Sponsoren ohne
CRM-Abfrage pro Tastendruck findet; ein Worker gleicht ihn mit Twenty ab.
RustFS hält private Dokumentbytes; Metadaten und Fachbezug liegen
im Core. Rendering und Versand verarbeiten transaktional erzeugte
Outbox-Ereignisse idempotent.

Web, PWA, Public und Campaign Site rufen den generierten
`@leonaid/api-client` auf. Sie dürfen Darstellung und Eingabe koordinieren,
aber keine maßgebliche Preis-, Rechte- oder Statuslogik besitzen. Caddy ist der
einzige veröffentlichte Laufzeiteinstieg. Eine Installation gehört genau zu
einem Club oder Träger; Isolation mehrerer Organisationen erfolgt durch
getrennte Installationen.

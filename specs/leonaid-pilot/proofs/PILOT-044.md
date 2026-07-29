# PILOT-044 – Technischer Nachweis

Stand: 2026-07-29  
Ergebnis: technische Admin-, Versions- und Vier-Augen-Basis sowie die
Public-Form-/Consent-Integration sind bewiesen; reale Fachwerte und ihre
Integration in Rechnung und Datenschutzworkflow bleiben offen.

## Implementierter Vertrag

- `/admin/legal` führt System-Admins in drei Schritten durch Träger und
  Rechnung, Datenschutz und Fristen sowie Prüfung und Freigabe.
- Jedes Feld besitzt eine kurze, graue Erklärung; die Abschlussansicht macht
  offene Grenzen sichtbar.
- Vier API-Endpunkte bilden Lesen, neuen unveränderlichen Entwurf,
  unabhängige Freigabe und Aktivierung ab.
- Globale System-Admin-Berechtigung, frischer Login und optimistische Revision
  werden serverseitig erzwungen.
- Eine zweite System-Administration muss den Entwurf freigeben. Der Ersteller
  darf seine eigene Version nicht freigeben.
- Offene oder erforderliche E-Rechnung und fehlende Nachweise blockieren die
  Aktivierung. In Produktion blockieren zusätzlich erkennbare
  Golden-/Test-/Platzhalterwerte.
- PostgreSQL speichert unveränderliche Versionen, separate Freigaben und
  genau eine aktive Version. Audit-Ereignisse enthalten keine vertraulichen
  Konfigurationswerte.
- Das Public Web liefert Datenschutzhinweis, Rechtsgrundlage, Kontakt und
  Consent-Textversion ausschließlich aus der aktiven Version. Ohne aktive
  Version bleibt die Aktion lesbar, aber Bestellungen sind fail-closed
  deaktiviert.
- Der Core weist ein bereits geöffnetes Formular nach einem Versionswechsel
  ab. Ein erfolgreicher Auftrag persistiert den geprüften Consent-Nachweis
  mit der aktiven Textversion und Status `confirmed`.
- [`LEGAL-CONFIGURATION-RUNBOOK.md`](../../../infra/pilot/LEGAL-CONFIGURATION-RUNBOOK.md)
  beschreibt fachlichen Schnitt, Rollen, sicheren Ablauf und verbleibende
  Abnahmegrenzen.

## Reproduzierbarer Test

Ausgeführt:

```text
./leonaid test-pilot-legal-config
```

Ergebnis:

```text
4 passed
1 passed
legal-configuration-contract: OK: Versionierung, Vier-Augen-Grenze,
Aktivierungsstopp und PII-freies Audit bewiesen
legal-configuration-test: OK: reale PostgreSQL-Versionierung,
legal-configuration-test:     Vier-Augen-Aktivierung und Browser-UX bewiesen
```

Der Test verwendet keine Mocks:

1. prüft die Produktionssperren und widersprüchliche Steuer-/Fristenwerte
   gegen den echten Domain-Code;
2. startet PostgreSQL, Twenty, RustFS, Mailpit, FastAPI, Web/PWA/Public und
   den Reverse Proxy in einem isolierten Compose-Projekt;
3. provisioniert Twenty, rendert reale Typst-PDFs und seedet das Golden
   Dataset;
4. beweist, dass ein Akquisiteur die Konfiguration nicht lesen darf;
5. legt Version 1 an, weist die Eigenfreigabe zurück und lässt eine zweite
   System-Administration freigeben;
6. blockiert die Aktivierung wegen offener E-Rechnungsentscheidung und weist
   einen veralteten Revisionsstand zurück;
7. bearbeitet Version 2 im echten Chromium, lässt sie durch die andere
   System-Administration freigeben und aktiviert sie;
8. prüft Desktop, Mobilansicht, schwere Accessibility-Verstöße,
   Browserfehler, unveränderte Version 1 und die exakte Audit-Sequenz;
9. entfernt das Testprojekt samt Containern, Netzen und Volumes.

Die sichtbare In-App-Browser-Prüfung hat dieselbe Seite zusätzlich im
laufenden Entwicklungsstack nachvollziehbar geöffnet. Die öffentliche
Golden-Aktion zeigt dort den dynamischen Datenschutzhinweis, die
Rechtsgrundlage, den verantwortlichen Kontakt und
`public-order-golden-v1`.

Die technische Public-Form-Integration wird ohne Mocks über
`./leonaid test-public-orders` bewiesen. Der Vertrag entfernt die aktive
Version kontrolliert, prüft das deaktivierte Formular, stellt sie wieder her,
weist eine veraltete Textversion ab und führt anschließend die drei realen
Bestellwege gegen FastAPI, PostgreSQL und Twenty aus.

## Bewusst offene Fach- und Integrationsgrenzen

- Das Repository enthält absichtlich keine realen Träger-, Bank-, Steuer-
  oder Datenschutzwerte. Diese müssen durch die zuständigen Rollen bestätigt
  und über die Admin-Oberfläche eingepflegt werden.
- Das aktionsbezogene Rechnungsprofil ist weiterhin der aktive Vertrag der
  Rechnungserzeugung. Seine Ableitung beziehungsweise Bestätigung gegen die
  aktive installationsweite Grundlage ist noch offen.
- Public Form und Consent-Erfassung verwenden die aktivierte Version.
  Datenschutzexport und Erasure verwenden die real bestätigten Fristen noch
  nicht.
- Ein realer Staging-Beleg und die private Produktivfreigabe fehlen.

PILOT-044 bleibt deshalb formal offen.

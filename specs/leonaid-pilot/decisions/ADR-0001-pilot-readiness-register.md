# ADR-0001: Pilot-Reife als explizites, extern freigegebenes Gate

- Status: angenommen
- Datum: 2026-07-28
- Entscheider: Produktverantwortlicher und Implementierung
- Externe Entscheider: rechtlicher Träger, Steuerberatung, Datenschutz und
  Betrieb gemäß Entscheidungsregister

## Kontext

Der PoC beweist Technik mit synthetischen Daten. Ein realer Pilot benötigt
zusätzlich Entscheidungen zu Trägerschaft, Datenschutz und Betrieb. Diese
Entscheidungen dürfen weder aus Golden Data abgeleitet noch stillschweigend
durch Implementierungsdefaults getroffen werden.

Einige Ergebnisse sollen später über das Admin-Backend gepflegt werden. Eine
freie Textsammlung wäre jedoch schwer prüfbar, könnte private Dokumente ins
System ziehen und würde technische Eingabemöglichkeiten mit fachlicher
Freigabe verwechseln.

## Entscheidung

`DECISIONS.md` ist zunächst das kanonische, maschinenlesbare Register. Jede
Entscheidung besitzt ID, Owner-Rolle, Datum, Quelle, externe Evidence-ID,
Status, kontrollierten Wert und spätestes Gate.

Die spätere Admin-Seite „Pilot-Reife“ baut ohne zweites Datenmodell auf diesem
Vertrag auf. Sie gruppiert die Entscheidungen in Träger, Steuer,
Datenschutz und Betrieb und darf:

- genehmigte Ergebnisse und deren Wirksamkeitsdatum erfassen;
- eine nicht personenbezogene Evidence-ID referenzieren;
- Auswirkungen, offene Punkte und blockierte Pilotaktionen anzeigen;
- bei Änderungen Fresh Login, Audit und Versionierung erzwingen.

Sie darf keine Rechts- oder Steuerentscheidung vorschlagen, keine Verträge
oder Zugangsdaten speichern und keine fachliche Freigabe vortäuschen.
Installationseinstellungen sind der Default; aktionsbezogene
Rechnungsprofile müssen vor Ausgabe einer Rechnung zusätzlich bestätigt
werden.

`pilot-doctor` validiert das Register und blockiert jede produktive
Pilotaktion, solange eine dafür fällige Entscheidung `open` oder `stop` ist.
Lokale Entwicklung, Golden-Data-Tests und der bestehende PoC bleiben davon
getrennt.

## Konsequenzen

- Offene externe Entscheidungen bleiben sichtbar und können nicht durch
  Codeänderungen „gelöst“ werden.
- Private Evidence bleibt außerhalb des Repositories und wird nur durch
  stabile IDs referenziert.
- Die Admin-UX kann schrittweise ergänzt werden, ohne einen zweiten
  Freigabevertrag einzuführen.
- Secrets werden weiterhin ausschließlich über den betrieblichen Secret Store
  verwaltet.


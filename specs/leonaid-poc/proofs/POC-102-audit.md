# POC-102 – UX-, Accessibility- und Content-Audit

Auditdatum: 2026-07-27  
Geprüfter Stand: LeonAid Core mit Golden Data v1  
Status: P0/P1 geschlossen

## Kurzurteil

Die drei kritischen Oberflächen führen ihre jeweilige Persona ohne
Datenbankwissen, interne IDs oder Twenty-Begriffe durch den Kernablauf. Die
visuelle Hierarchie ist klar, die primäre Handlung bleibt erkennbar und
Statusinformationen besitzen neben Farbe stets Text oder Semantik.

Der erste reale Browserlauf fand drei P1-Befunde. Alle drei wurden im selben
Task geschlossen und mit demselben Golden Scenario erneut bewiesen. Es gibt
keine offenen P0- oder P1-Befunde.

| Qualitätsdimension                   | Bewertung | Begründung                                                         |
| ------------------------------------ | --------: | ------------------------------------------------------------------ |
| Aufgabenführung und Hierarchie       |      9/10 | Je Persona ein klarer Einstieg und ein dominanter nächster Schritt |
| Informationsarchitektur              |      9/10 | Fachbereiche, Rollen und Aktionskontext bleiben sichtbar           |
| Fachsprache und Fehlermeldungen      |      9/10 | Kein Technikjargon; Fehler nennen Auswirkung und Korrektur         |
| Tastatur und Screenreader-Semantik   |     10/10 | Fokusziele, Labels, Status und Fortschritt maschinenlesbar         |
| Responsive Verhalten und Text-Zoom   |      9/10 | Smartphone, Desktop und 200 Prozent ohne Seitenüberlauf            |
| Wahrgenommene und gemessene Leistung |      9/10 | Alle drei Kernseiten deutlich innerhalb der PoC-Budgets            |

Gesamturteil: **93/100 – abnahmefähige PoC-Basis**.

## Priorisierte Befunde

### Geschlossene P1-Befunde

| ID     | Beobachtung                                                                  | Auswirkung                                                             | Korrektur                                                                            |
| ------ | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| UX-101 | Der Skip-Link änderte die URL, setzte den Fokus aber nicht auf den Inhalt.   | Tastaturnutzer mussten erneut durch die gesamte Navigation tabben.     | Beide Hauptinhalte sind explizite, nicht sequenziell tabbende Fokusziele.            |
| UX-102 | Native Formularvalidierung fokussierte ein Feld ohne zusammenfassenden Text. | Es blieb unklar, ob die Bestellung gesendet wurde und was folgt.       | Das Formular nennt Nichtversand, markierte Felder und erneutes Absenden.             |
| UX-103 | Die Desktop-Rechnungsliste lief bei 200 Prozent Text horizontal über.        | Inhalte und Aktionen konnten außerhalb des sichtbaren Bereichs liegen. | Containerabhängiges Reflow und umbrechende Filterleiste ersetzen starre Breakpoints. |

### Offene P2/P3-Beobachtungen

- **P2 – JavaScript-Startgröße:** PWA und Admin bleiben unter dem vereinbarten
  Transferbudget, ihre Produktionsbuilds melden aber jeweils einen
  JavaScript-Chunk über 500 kB. Vor einem breiten Produktivrollout sollte
  routenbezogenes Code-Splitting folgen.
- **P3 – lange Formulare bei großem Text:** Die vollständige Bestellerfassung
  benötigt bei 200 Prozent erwartbar viel vertikales Scrollen. Abschnittsnummern,
  Zwischenstand und feste PWA-Navigation erhalten dabei den Kontext; ein
  mehrseitiger Wizard wäre im aktuellen PoC unnötige Zustandskomplexität.

## Heuristische Prüfung

| Heuristik                        | Ergebnis im kritischen Flow                                                                 |
| -------------------------------- | ------------------------------------------------------------------------------------------- |
| Sichtbarkeit des Systemstatus    | Zielstand, Filter, Bestellwert, Speichern und Versandzustand sind explizit.                 |
| Übereinstimmung mit der Fachwelt | Firma, Sponsor, Bestellung, Rechnung und Aktion ersetzen technische Objektnamen.            |
| Kontrolle und Rückweg            | Zurücklinks, Filter und Entwurfsoption verhindern Sackgassen.                               |
| Konsistenz                       | Gemeinsame Shell, Tokens, Felder, Statuschips und Aktionsmuster werden wiederverwendet.     |
| Fehlervermeidung                 | Pflichtfelder, Hilfetexte, Live-Summe und verbindliche Bestätigung stehen vor dem Absenden. |
| Wiedererkennen statt Erinnern    | Aktionskontext, Sponsor, Angebot, Menge und Rechnungsempfänger bleiben sichtbar.            |
| Effizienz                        | Dashboard-Kennzahlen führen direkt in vorgefilterte Arbeitslisten.                          |
| Minimalismus                     | Pro Abschnitt ist eine Entscheidung dominant; Technikdetails bleiben verborgen.             |
| Fehlerbehandlung                 | Problem, Auswirkung und nächster Schritt werden zusammen genannt.                           |
| Hilfe im Kontext                 | Kurze graue Feldbeschreibungen erklären Zweck und spätere Verwendung.                       |

## Persona- und Cognitive-Load-Kritik

### Charity-Admin

Klara benötigt auf dem Desktop eine schnelle Lagebeurteilung, keine
Systemkonsole. Dashboard und Rechnungsliste priorisieren deshalb offene
Arbeit, Betrag und Status. Die Smartphone-Ansicht bleibt als responsiver
Kontrollweg nutzbar, ohne eine zweite Produktlogik einzuführen.

### Akquisiteurin

Anna arbeitet primär mit einer Hand am Smartphone. Der persönliche nächste
Schritt führt direkt zum passenden Sponsor und von dort in eine vorausgefüllte
Bestellerfassung. Angebot, Menge, Rechnungsempfänger und Zusammenfassung
reduzieren Gedächtnislast. Die identische Fachfunktion bleibt am Desktop
nutzbar.

### Öffentlicher Besteller

Die Seite erklärt Wirkung vor Datenerhebung. Im Formular folgen Auswahl,
Kontakt, Lieferung, Rechnung und Bestätigung der mentalen Reihenfolge einer
Bestellung. Bei einem Fehler bleiben Eingaben erhalten; der Fokus springt zum
ersten Feld und eine Meldung erklärt, dass noch nichts gesendet wurde.

## Anti-Pattern-Prüfung

- keine internen IDs oder CRM-Objektnamen als Nutzerlabels;
- keine farbexklusive Statusinformation;
- keine Icon-only-Kernaktion ohne zugänglichen Namen;
- keine horizontal scrollende Gesamtseite bei 200 Prozent Text;
- keine inaktive Schaltfläche ohne sichtbare Erklärung;
- keine unnötige Dashboard-Kartenwand: Kennzahlen führen zu Arbeit;
- keine Browser-only-Fachlogik für Preise, Rollen oder Persistenz.

## Empfehlung nach dem PoC

Die aktuelle Basis sollte beibehalten werden. Als nächste UX-Investition ist
routenbezogenes Code-Splitting wertvoller als eine visuelle Neugestaltung.
Lions Open und Weihnachtsmarkt sollten erst nach ihrem eigenen
Golden-Scenario-Audit zusätzliche Navigationspunkte oder Formmuster erhalten.

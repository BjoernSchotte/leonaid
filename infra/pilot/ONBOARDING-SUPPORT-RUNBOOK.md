# Pilot-Onboarding und Support

Dieses Runbook beschreibt den reproduzierbaren Ablauf für `PILOT-051`. Es
richtet sich an Club-Verantwortliche und Operatoren; Datenbankzugriff,
interne IDs und Einsicht in fachliche Formulardaten sind nicht erforderlich.
Ein technischer Testlauf ersetzt weder einen bestätigten Pilotkreis noch
moderierte Sitzungen mit realen Personen.

## Rollen und Grenzen

- **System-Admin** lädt Mitglieder ein, verwaltet installationsweite Rollen,
  sperrt Konten, entzieht Sitzungen und bearbeitet technische Support-Codes.
- **Charity-Admin** lädt Mitglieder ausschließlich in selbst verwaltete
  Aktionen ein und verwaltet deren aktionsbezogene Rollen.
- **Akquisiteur** pflegt Sponsoren und Zusagen für zugeordnete Aktionen.
- **Finanzen** prüft, erzeugt, versendet und verbucht Rechnungen.
- **Pilot-Koordination** bestätigt Pilotkreis, Zeitraum, Datenschutzinformation,
  Supportfenster und Abbruchkriterien außerhalb von LeonAid.

Jede reale Person erhält einen individuellen Account. Geteilte Konten,
weitergeleitete Login-Codes und die Änderung einer E-Mail-Adresse durch das
Mitglied selbst sind im Pilot ausgeschlossen.

## 1. Pilot vor dem ersten Login bestätigen

Die Pilot-Koordination hält im privaten Evidence Store fest:

1. freigegebene reale Personen und ihre benötigten Rollen;
2. verwaltete Charity-Aktionen je Charity-Admin;
3. Beginn, Ende, Supportzeiten und erreichbaren Eskalationskanal;
4. übermittelte Datenschutzinformation und rechtmäßige Datenverwendung;
5. Release-ID und Commit des freigegebenen Stands;
6. Abbruchkriterien für Datenschutz-, Autorisierungs- oder Datenverlustverdacht.

In das Repository gehören nur eine nicht erratbare Evidence-ID und
personenbezugsfreie Summen. Namen, E-Mail-Adressen, Login-Codes und
Supportinhalte bleiben im geschützten Evidence Store.

## 2. Mitglied einladen und ersten Zugang prüfen

1. Als System-Admin `Mitglieder` öffnen und `Mitglied einladen` wählen.
2. E-Mail-Adresse einmal gegen die bestätigte Pilotliste prüfen.
3. Nur die benötigte installationsweite Rolle vergeben.
4. Für eine Aktionsrolle die konkrete Charity-Aktion auswählen.
5. Einladung absenden. Die Zuordnung gilt nach bestätigter Einladung sofort.
6. Die eingeladene Person fordert auf `Login` selbst einen Code an und meldet
   sich damit an.
7. Gemeinsam prüfen, dass Navigation und Arbeitskontext nur die vorgesehenen
   Bereiche zeigen.

Ein Charity-Admin wiederholt dieselbe Strecke für eine selbst verwaltete
Aktion. Der negative Nachweis muss zeigen, dass fremde Aktionen nicht
ausgewählt oder beschrieben werden können.

## 3. Rolle ändern, Konto sperren und Sitzung entziehen

Diese Aktionen werden ausschließlich in `Mitglieder` ausgeführt:

1. betroffenes Mitglied öffnen;
2. Rolle oder aktionsbezogene Zuordnung ändern und speichern;
3. bei Entzug sofort `Sitzungen entziehen` ausführen;
4. für Offboarding zusätzlich das Konto sperren;
5. mit einer frischen Anmeldung prüfen, dass entzogene Bereiche nicht mehr
   erreichbar sind.

Wichtige Administrationsaktionen verlangen eine frische Anmeldung. Eine
E-Mail-Korrektur führt im Pilot der System-Admin aus; das Mitglied kann die
Adresse nicht selbst ändern. Direkte Datenbankänderungen gelten als
fehlgeschlagener Operatornachweis.

## 4. Support-Code an die Betreuung geben

Jede normale API-Fehlermeldung nennt Auswirkung, nächsten Schritt und einen
Support-Code. Die betroffene Person übermittelt ausschließlich:

- den vollständigen Support-Code;
- den groben Arbeitsbereich;
- den beobachteten Zeitpunkt;
- ob ein erneuter Versuch bereits erfolgt ist.

Nicht mitsenden: Formularinhalte, Namen, E-Mail-Adressen, Adressen,
Login-Codes, Cookies, Tokens, Screenshots mit Echtdaten oder Dokumente.

## 5. Anfrage als System-Admin sicher diagnostizieren

1. `System & Betrieb` öffnen.
2. Unter `Anfrage sicher nachvollziehen` den vollständigen Support-Code
   einfügen.
3. `Sicher nachschlagen` wählen.
4. Ergebnis, Auswirkung, Route, Status, Fehlercode, Release und nächsten
   Schritt prüfen.
5. Betriebsstatus und das zum Fehlercode passende Runbook abarbeiten.
6. Erst danach genau einen erneuten Fachversuch anleiten.

Die Diagnose speichert pro API-Prozess höchstens die letzten 2.000 Anfragen
und nur:

- Support-Code und Zeitpunkt;
- HTTP-Methode und normalisierte Routenvorlage;
- HTTP-Status und stabilen Fehlercode;
- Release.

Query-Parameter, Request-/Response-Payloads, Header, Identitäten und
fachliche Daten werden nicht gespeichert. Nach Prozessneustart ist der
Ringpuffer leer. Wird ein Code nicht gefunden, wird die Aktion höchstens
einmal kontrolliert reproduziert; niemals werden dafür Payloads oder
Datenbankinhalte ausgelesen.

Der Button `Diagnose-Test starten` erzeugt absichtlich einen
schreibfreien Fehler `support_probe_failed`. Er dient nur dem Training und
darf nicht als echter Incident gezählt werden.

## 6. Feedback datensparsam erfassen

Die Vorlage [`FEEDBACK-TEMPLATE.md`](FEEDBACK-TEMPLATE.md) wird pro
Beobachtung im privaten Evidence Store kopiert. Der Koordinator entfernt
unnötige personenbezogene Angaben, priorisiert den Befund und ordnet ihn
einer Release-ID zu. Öffentliche Nachweise enthalten nur aggregierte Counts,
Priorität, Status und eine nicht erratbare Evidence-ID.

Vor Pilotaktivierung müssen P0/P1-Usability- und Accessibility-Befunde
geschlossen und erneut nachgewiesen sein. P2 benötigt Owner, Zielrelease und
eine explizite Pilotentscheidung.

## 7. Eskalation und Abschluss

- **P0:** Pilot sofort stoppen, Schreibzugriffe sperren, Incident- und
  Recovery-Runbook anwenden.
- **P1:** betroffene Strecke deaktivieren oder Zugang begrenzen; vor
  Wiederaufnahme Fix und Regression beweisen.
- **P2/P3:** Owner, Release und Entscheidung dokumentieren.

Beim Offboarding werden Rollen entfernt, Sitzungen entzogen und das Konto
gesperrt. Die Person bestätigt anschließend, dass eine frische Anmeldung
keinen Zugriff mehr ermöglicht. Der Koordinator erfasst nur die private
Evidence-ID und ein personenbezugsfreies Ergebnis.

## Reproduzierbarer technischer Teilnachweis

```sh
./leonaid test-unit
./leonaid test-operations
```

`test-operations` verwendet einen leeren, isolierten Stack mit echtem
PostgreSQL, Twenty, RustFS, Mailpit, Worker und Browser. Er erzeugt den
kontrollierten Fehler, korreliert seinen Support-Code, prüft die
Payloadfreiheit sowie System-Admin-Schutz und räumt Container, Netzwerke und
Volumes anschließend auf.

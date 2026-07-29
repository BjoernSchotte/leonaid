# Live-Pilot: technischer Tagescheck

Dieses Runbook beschreibt den technischen Tagescheck für einen begrenzten
LeonAid-Pilot. Es ersetzt weder die fachliche Pilotfreigabe noch die offenen
Träger-, Steuer-, Datenschutz- oder Betriebsentscheidungen.

## Verantwortlichkeit und Rhythmus

Ein benannter System-Admin führt den Check an jedem Pilottag vor Beginn des
Nutzungsfensters und nach jedem P0-/P1-Vorfall aus:

1. im Portal `System & Betrieb` öffnen;
2. `Tagesreport erstellen` wählen;
3. Status, sechs Betriebsbereiche, Stop-Gründe und nächsten Schritt lesen;
4. den JSON-Report herunterladen;
5. ihn im privaten, zugriffsbeschränkten Pilot-Evidence-Bereich ablegen;
6. bei `blockiert` den Pilot nicht starten beziehungsweise sofort stoppen;
7. bei `Aufmerksamkeit` den Befund einem Owner und Termin zuordnen.

Der Report wird immer neu aus dem aktuellen Systemzustand erzeugt. Alte
Downloads sind keine Aussage über den heutigen Zustand.

## Abgedeckte Bereiche

Der Report führt ausschließlich technische und aggregierte Werte zusammen:

- jüngster Backupstatus;
- offene Alerts nach Priorität;
- Outbox-Bestand und Dead Letters;
- verfügbarer Speicher;
- TLS-Zertifikatsstatus;
- Erreichbarkeit von Core-Datenbank, Twenty, RustFS und Mail-Provider.

Er enthält keine Namen, E-Mail-Adressen, Sponsor-, Bestell-, Rechnungs-,
Zahlungs-, Request- oder Response-Payloads.

## Status und Stop-Gründe

- `bereit`: kein technischer Blocker und kein technischer
  Aufmerksamkeitsbefund;
- `Aufmerksamkeit`: der Pilot kann technisch weiterlaufen, der Befund braucht
  aber Owner und Termin;
- `blockiert`: mindestens ein stabiler Stop-Grund liegt vor.

Ein P0/P1-Alert, ein kritischer oder fehlender Backup-, Speicher- oder
TLS-Check, ein Dead Letter, ein inaktiver beziehungsweise nicht erreichbarer
Monitor oder eine nicht erreichbare Kernabhängigkeit blockiert. Die
maschinenlesbaren Stop-Gründe im Report sind die führende Diagnose. Der
angezeigte nächste Schritt nennt die sichere Operatoraktion.

`bereit` bedeutet ausdrücklich nicht, dass der Live-Pilot fachlich,
datenschutzrechtlich oder organisatorisch freigegeben ist. Dafür bleiben die
Freigaben und Stopkriterien aus `PILOT-001`, `PILOT-044`, `PILOT-050` bis
`PILOT-053` maßgeblich.

## Integritätsprüfung

Der Response-Header `X-Content-SHA256` und das Feld `checksumSha256` enthalten
dieselbe Prüfsumme. Sie wird über die UTF-8-kodierte, kompakte JSON-Darstellung
des Reports ohne `checksumSha256` berechnet; Objektschlüssel werden
lexikografisch sortiert, Nicht-ASCII-Zeichen als JSON-Escapes geschrieben.

Ein abweichender Hash macht den Download als Evidence ungültig. Der Report
wird dann erneut direkt aus dem Portal erzeugt. Wiederholt sich die
Abweichung, wird der Pilot gestoppt und ein P1-Incident eröffnet.

## Incident und Tagesabschluss

Bei einem Stop-Grund gilt:

1. keine technische Freigabe erteilen beziehungsweise Pilot stoppen;
2. Support-Code, Release, Stop-Grund und Zeitpunkt ohne Personenbezug
   festhalten;
3. das zuständige Runbook für Backup, Alert, Outbox, Speicher, TLS oder
   Abhängigkeit ausführen;
4. nach Behebung einen neuen Tagesreport erzeugen;
5. nur mit geschlossenem P0/P1 und den erforderlichen fachlichen Freigaben
   fortfahren.

Zum Tagesabschluss werden Volumen, Fehlerraten, Supportfälle, Wiederanläufe
und offene P2/P3 aggregiert erfasst. Ein einzelner Tagesreport ist noch kein
Abschlussreport und beweist noch keinen tatsächlich durchgeführten
Live-Pilot.

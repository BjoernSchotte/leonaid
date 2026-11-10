---
title: Bekannte Grenzen
description: Belegte Grenzen des aktuellen LeonAid-Entwicklungs- und Pilotstands.
docId: DOC-P003
audience: [user, ops, dev]
diataxis: reference
contentRevision: 13
reviewedRevision: 13
verifiedAgainst: 62502ee563a1d1e95e675e8040a6e6fcb6cea887
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

Diese Dokumentation beschreibt den aktuellen Entwicklungsstand. Sie ist keine
allgemeine Produktionsfreigabe.

- Die Produktoberfläche und die von ihr versendeten Texte sind derzeit
  deutschsprachig. Die englische Dokumentation nennt deutsche UI-Labels
  wörtlich.
- Eine Installation bildet einen Club beziehungsweise einen getrennten
  Mandanten ab. Gemeinsamer Mehrmandantenbetrieb ist nicht vorgesehen.
- Ausfahrer haken ihre zugewiesenen Lieferungen in der App ab (siehe
  [Auslieferung abhaken](/de/user/how-to/work-delivery-board/)). Die Tourenplanung
  (Feature-Flag `delivery.tours`, siehe
  [Lieferrouten planen](/de/user/how-to/plan-delivery-tours/)) hat Grenzen:
  keine Straßenrouten (nur Luftlinie), keine Live-Ortung der Fahrer, eine Tour
  je Fahrer und Liefertag. Der öffentliche Nominatim-Dienst und die
  OSM-Kacheln unterliegen deren Nutzungsbedingungen; bei hohem Aufkommen ist
  ein eigener Anbieter zu konfigurieren.
- Benachrichtigungen der Akquise-App (Feature-Flag `pwa.push`, siehe
  [Benachrichtigungen einschalten](/de/user/how-to/switch-on-notifications/))
  haben Grenzen: Die Zustellung über die Push-Dienste von Google, Mozilla,
  Apple und Microsoft ist nicht automatisch getestet, nur das Senden an einen
  entschlüsselnden Empfänger und die Anzeige im Browser; die Prüfung auf
  einem echten Android-Telefon und iPhone ist Handarbeit. iPhone und iPad
  brauchen LeonAid auf dem Home-Bildschirm. Es gibt vier Arten
  (Wiedervorlagen einmal am Tag ab 8 Uhr, neue Bestellungen, Aufgaben,
  Lieferungen), höchstens eine Benachrichtigung je Art in 15 Minuten, keine
  Ruhezeiten und keine Einstellung je Gerät. Eine Benachrichtigung nennt nur
  Art und Anzahl. Sie ist ein Hinweis ohne Zustellgarantie. Nach dem
  Abmelden schaltet das Mitglied das Gerät neu ein; nach 90 Tagen ohne Öffnen
  der App kommt nichts mehr, bis sie wieder geöffnet wird. Ein Mitglied kann
  höchstens zehn Geräte anmelden. Ein neuer `LEONAID_VAPID_PRIVATE_KEY`
  beendet alle Anmeldungen; jedes Gerät meldet sich beim nächsten Öffnen der
  App von selbst neu an.
- `finance_reader` darf Belege nur lesen. Der gepflegte Demo-Benutzer Finn
  Finanzen beweist genau diesen Lesezugriff. Zahlungen und Storno benötigen
  `finance_manager` oder den Charity-Admin der betroffenen Aktion.
- Mitglieder können ihre Login-E-Mail nicht selbst ändern. Ein System-Admin
  stößt den Wechsel an; die neue Adresse muss ihn bestätigen.
- Öffentliche Bestellungen sind nur für eine veröffentlichte Aktion mit
  aktivem Bestellformular und verfügbarem Angebot möglich. Bei aktivierter
  Lieferplanung ist außerdem ein verfügbares Lieferfenster nötig.
- Bestellbestätigung und Stornohinweis gehen als reiner Text an Besteller aus
  dem öffentlichen Formular. Für Bestellungen, die Mitglieder oder
  Akquisiteure erfassen, schaltet die Aktionsverwaltung sie je Aktion ein
  (**E-Mails an Käufer**); dann wird eine Bestellung einmal bestätigt, sobald
  sie prüfbereit ist. Bestellungen ohne E-Mail-Adresse des Käufers und Entwürfe
  erhalten keine E-Mail, ebenso Bestellungen, die erst nach der Lieferung,
  nach dem Lieferfenster oder nach Abschluss der Aktion prüfbereit werden;
  das gilt auch für Bestellungen aus dem öffentlichen Formular. Konnte
  LeonAid eine rechtzeitig angelegte Bestätigung erst danach senden (Versand
  gestört), geht sie nicht mehr hinaus und steht in der Bestellung als
  fehlgeschlagen.
  Bestellungen von vor dem Einschalten bestätigt die Aktionsverwaltung
  einzeln in der Bestellung (**Senden**). Die Adresse ist die des Sponsors
  aus dem CRM. LeonAid prüft nicht, ob die Datenschutzerklärung des Clubs
  diese E-Mails nennt. Die E-Mail am Liefertag (je Aktion einschaltbar, für
  Bestellungen jeder Herkunft) nennt nur das Lieferfenster: keine
  Ankunftszeit je Adresse, kein Fahrer, keine Nachricht bei Verspätung oder
  wenn ein Fenster verlegt wird. Sie geht bis zu fünf Minuten nach der
  gewählten Uhrzeit hinaus und enthält keinen Link zur Aktionsseite. Ein
  Lieferfenster, das vor dieser Uhrzeit endet, erhält keine E-Mail; die
  Bestellung zeigt das an. Nach der Lieferung, für stornierte Bestellungen
  und in einer abgeschlossenen Aktion geht sie nicht mehr hinaus.
  Bestellnummern haben zwei Formen: neue sind kurz (`LA-` und acht Zeichen),
  öffentliche Bestellungen von früher behalten ihre lange Nummer. Der Link zur Aktion zeigt auf die dauerhafte Adresse
  der Aktion auf ihrer Kampagnen-Domain, sonst auf die Aktionsseite des
  öffentlichen Hosts. Absender ist die konfigurierte Systemadresse, nicht der
  Club.
- Die Suche (**Suchen und Befehle**) findet Sponsoren nur über Name und Ort
  und nur, wenn sie in einer Aktion einem Akquisiteur zugeordnet sind (siehe
  [Mit der Suche finden](/de/user/how-to/find-with-search/)). E-Mail, Telefon
  und Straße sind nicht durchsuchbar. Eine Änderung im CRM erreicht die Suche
  nach bis zu etwa 15 Minuten; ein im CRM gelöschter Sponsor verschwindet erst
  in der folgenden Nacht. Bis dahin öffnet sein Treffer die Zuordnung, die
  dann „Im CRM nicht mehr vorhanden“ heißt und keine Kontaktdaten zeigt.
  Die Akquise-App hat keine eigene Suche.
- Ein gespeicherter Rechnungsbeleg und sein PDF werden nicht nachträglich
  überschrieben. Korrekturen erfolgen durch Storno und einen neuen Vorgang.
- Ein Storno stellt eine Stornorechnung mit eigener Nummer aus dem
  Nummernkreis der Rechnungen aus. Es gibt nur das vollständige Storno: kein
  Teilstorno und keine Korrekturrechnung, die Positionen ersetzt. Zu einer
  Bestellung gibt es eine Rechnung; eine korrigierte Rechnung braucht eine neue
  Bestellung. Rechnungen, die vor dieser Funktion storniert wurden, haben keine
  Stornorechnung, bis jemand sie ausstellt. Der Wortlaut der Stornorechnung ist
  ein Vorschlag und rechtlich noch nicht geprüft.
- Zahlungen einer stornierten Rechnung bleiben erfasst und lassen sich nicht
  zurückbuchen. LeonAid bucht keine Erstattung; „Erstattung erledigt“ ist nur
  ein Vermerk. Er lässt sich mit Grund zurücknehmen.
- Teil- und Überzahlungen werden als einzelne Zahlungseinträge erfasst und
  bei Bedarf begründet zurückgebucht. Eine Überzahlung wird nur angezeigt; die
  Erstattung läuft außerhalb von LeonAid. Bankabgleich und Mahnwesen fehlen.
- Eine Installation bedient einen Host oder einen Verwaltungshost
  (`app.<domain>`) plus einen öffentlichen Host mit weiterleitenden
  Zusatznamen (Stufe 1 von `specs/multi-domain/PLAN.md`). Eigene
  Kampagnen-Domains lassen sich unter **System › Domains** eintragen, prüfen
  und mit Aktionen verbinden; sie zeigen nur Kampagnenseiten aus dem CMS.
  Die Abnahme mit einer echten Domain und echten Zertifikaten steht aus. Eine Installation
  ohne öffentlichen Host lässt sich einrichten (`pilot-secrets --no-public-host`). `/` auf dem Verwaltungshost ist der
  rollenbasierte Einstieg (Anmeldung, dann Startbereich). Beim Umstellen auf zwei Hosts meldet sich
  jedes Mitglied einmal neu an (`pilot-revoke-sessions`). Auf dem
  öffentlichen Host zeigt die Kopfzeile statt der persönlichen App-Links einen
  festen Link „Mitgliederbereich“: die Sitzung gehört zum Verwaltungshost.
- Aktionsseiten laufen in einer Pilotinstallation mit
  `LEONAID_CMS_ENABLED=true`. Ihre einmalige Einrichtung in Produktion
  (CMS-Datenbankrolle, Medien-Bucket, Editor-Setup) hat noch keinen
  `pilot-*`-Befehl.
- Listmonk (Compose-Profil `mailing`) gehört nicht zum produktiven
  Pilot-Stack. Dort hat es weder öffentliche Route noch Backup noch
  Monitoring; alle drei müssen vor dem Aktivieren des Profils existieren.
- Die getrennte Dokumentationswebsite wird als statische GitHub-Pages-Site aus
  dem geprüften Artefakt veröffentlicht. Bis zur öffentlichen Abnahme sind die
  versionierten Quellen und CI-Artefakte der belastbare Zugang.

## Hinweise zur Dokumentationswebsite

Björn Schotte pflegt die Website über das öffentliche
[LeonAid-Repository](https://github.com/BjoernSchotte/leonaid). Fehler können
dort als Issue gemeldet werden. Die statische Site setzt keine eigene Analyse
ein und benötigt keine Anmeldung. GitHub verarbeitet beim Hosting technische
Zugriffsdaten nach seiner
[Datenschutzerklärung](https://docs.github.com/de/site-policy/privacy-policies/github-general-privacy-statement).

Für LeonAid ist noch keine Open-Source-Lizenz gewählt. Die Dokumentation ändert
diesen Status nicht; Lizenzen eingebundener Komponenten gelten unabhängig.

Melde eine Abweichung mit dem betroffenen Produktpfad, der sichtbaren Meldung
und dem verwendeten Commit. Die Implementierung bleibt die Wahrheitsquelle.

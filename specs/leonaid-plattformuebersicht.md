# LeonAid - aktueller Stand und Weg zum Pilotbetrieb

**Stand:** 10. August 2026  
**Betrachteter Umfang:** Krapfentaxi als erster durchgängiger Anwendungsfall

## Worum es in diesem Dokument geht

LeonAid ist eine gemeinsame Plattform für Charity-Aktionen eines Lions-Clubs.
Sie verbindet drei Perspektiven:

- Lions-Mitglieder arbeiten im internen Portal oder unterwegs in der
  mobilen Akquisiteur-App.
- Externe Unterstützer informieren sich auf einer öffentlichen Aktionsseite
  und können dort beispielsweise Krapfenboxen bestellen.
- Im Hintergrund werden Kontakte, Bestellungen, Rechnungen, Dokumente und
  Betriebsaufgaben zusammengeführt.

Dieses Dokument erklärt den Stand bewusst ohne technische Detailtiefe. Es
unterscheidet zwei Zustände:

### Aktuell vorhanden

Die Funktion ist umgesetzt und mit einem künstlichen, aber realistischen
Testbestand durchgespielt. Der vollständige Krapfentaxi-Ablauf funktioniert
vom ersten Login bis zur bezahlten Rechnung. Der lokale Demonstrationsbetrieb
läuft mit den vorgesehenen Diensten und Oberflächen.

### In Entwicklung

Die Funktion oder der organisatorische Nachweis ist für den begrenzten
Pilotbetrieb noch offen. Häufig fehlt nicht mehr die eigentliche Oberfläche,
sondern die Verbindung mit einem echten Anbieter, echten Clubdaten oder eine
verbindliche Freigabe durch Träger, Steuerberatung, Datenschutz oder Betrieb.

**Wichtig:** „Aktuell vorhanden“ bedeutet nicht automatisch „für den
Produktivbetrieb freigegeben“. Der aktuelle Prototyp ist abgeschlossen. Der
Pilotbetrieb bleibt gesperrt, bis die offenen fachlichen und betrieblichen
Entscheidungen getroffen und praktisch nachgewiesen wurden.

## 1. Überblick über die Personas

Eine Persona beschreibt einen typischen Menschen mit einem bestimmten Ziel.
Eine Person kann mehrere Rollen übernehmen, zum Beispiel Charity-Admin und
Akquisiteur. Berechtigungen für eine Charity-Aktion gelten nur für diese
Aktion.

### Aktuell vorhandene Personas

| Persona | Hauptziel | Typische Oberfläche |
| --- | --- | --- |
| **Charity-Admin** | Eine Charity-Aktion vorbereiten, steuern und abschließen | Internes Portal, vor allem am Desktop |
| **Akquisiteur** | Firmen und Personen als Sponsoren gewinnen und Zusagen festhalten | Mobile, installierbare Web-App |
| **Öffentlicher Besteller oder Sponsor** | Die Aktion verstehen und ohne Benutzerkonto bestellen | Öffentliche Aktionsseite auf Smartphone oder Desktop |
| **Finanzverantwortlicher oder Schatzmeister** | Rechnungen, Versand, Zahlungen und offene Beträge prüfen | Finanzbereich des internen Portals |
| **System-Admin** | Benutzer, Rechte, Betrieb und angebundene Dienste sicher verwalten | Systembereich des internen Portals |

### In Entwicklung oder nachgelagert

- **Reale Pilotnutzer:** Die Rollen und Oberflächen sind vorhanden. Noch
  offen sind die Benennung des kleinen Pilotkreises, die individuellen
  Einladungen, moderierte Nutzungstests und die Einführung durch einen
  unabhängigen Betreiber.
- **Ausfahrer:** Die Rolle ist im Modell vorgesehen, aber Tourenplanung,
  Stoppliste, Navigation und Zustellstatus sind ausdrücklich nicht Teil des
  aktuellen Piloten.
- **Ansprechpartner begünstigter Organisationen:** Begünstigte Organisationen
  werden einer Aktion zugeordnet. Ihre Ansprechpartner sind derzeit externe
  Beteiligte und haben noch kein eigenes LeonAid-Portal.
- **Weitere aktionsbezogene Rollen:** Spieler und Turnierleitung für Lions
  Open sowie Standbetreiber und Helfer für den Weihnachtsmarkt werden erst
  mit diesen späteren Anwendungsfällen konkretisiert.

## 2. Durchgängiger Kernablauf des Krapfentaxis

Der durchgängige Kernablauf - in der Produktentwicklung auch „Walking
Skeleton“ genannt - ist der kleinste Ablauf, der bereits wie das spätere
Gesamtsystem funktioniert. Beim Krapfentaxi reicht er von der
Vorbereitung der Aktion über Sponsorengewinnung und öffentliche Bestellung
bis zu Rechnung, Zahlung und Auswertung.

### 2.1 Charity-Admin

#### Aktuell vorhanden

1. **Anmelden:** Der Charity-Admin meldet sich ohne Passwort per E-Mail-Link
   oder sechsstelligen Code an. Die Sitzung kann lange bestehen bleiben;
   wichtige Änderungen verlangen nochmals eine frische Bestätigung.
2. **Aktion vorbereiten:** Name, Zeitraum, Ziel, begünstigte Organisationen,
   öffentliche Beschreibung, Angebote und Veröffentlichungszeitraum werden
   gepflegt. Eine kurze Adresse wie `/krapfentaxi` zeigt auf die aktuell aktive
   Aktion; ältere Aktionen können im Archiv erhalten bleiben.
3. **Mitglieder einbinden:** Der Charity-Admin kann Mitglieder in selbst
   verwaltete Aktionen einladen und dort passende Aktionsrollen vergeben.
   Globale System- oder Finanzrollen bleiben ausgeschlossen.
4. **Sponsorengeschehen überblicken:** Firmen, Kontakte, zuständige
   Akquisiteure, Aktivitäten, Wiedervorlagen und Mehrfachzuordnungen sind
   sichtbar.
5. **Bestellungen bearbeiten:** Interne Zusagen und öffentliche Bestellungen
   laufen in einer gemeinsamen Arbeitsliste zusammen. Quelle, Menge, Preis,
   Besteller und Rechnungsempfänger bleiben nachvollziehbar.
6. **Rechnung erstellen:** Aus einer prüfbereiten Bestellung kann nach
   frischer Anmeldung eine Rechnung freigegeben werden. LeonAid erzeugt ein
   unveränderliches PDF und ordnet es Aktion, Bestellung, Firma oder Kontakt
   sowie Rechnung zu.
7. **Versand und Zahlung verfolgen:** Versandstatus, Wiederholungsversuche,
   offene Rechnung, manuelle Vollzahlung und begründetes Storno sind im
   Portal nachvollziehbar.
8. **Fortschritt verstehen:** Die Übersichtsseite zeigt den Stand der
   Sponsorengewinnung, Bestellmenge, Bestellwert, den bereits in Rechnung
   gestellten Betrag, offene Posten und das
   manuell gepflegte Aktionsziel. Von Kennzahlen gelangt man direkt in die
   passende gefilterte Arbeitsliste.

#### In Entwicklung

- Die echten Träger-, Bank-, Rechnungs- und Steuerangaben müssen fachlich
  bestätigt und für den Pilot freigegeben werden.
- Die finalen Datenschutztexte, Aufbewahrungsfristen und Löschregeln müssen
  durch die zuständigen Stellen bestätigt werden.
- Ein Charity-Admin soll die vollständige Generalprobe mit echten
  Pilotdaten und produktivem Mailversand ohne Hilfe des Projektteams
  durchführen.
- Der Pilot muss zeigen, dass Einladung, Rollenwechsel, Sperrung und
  das Entfernen von Zugängen anhand der Dokumentation im realen Betrieb
  sicher gelingen.

### 2.2 Akquisiteur

#### Aktuell vorhanden

1. **Mobil anmelden:** Der Akquisiteur öffnet die installierbare Web-App und
   meldet sich per E-Mail-Code oder Link an.
2. **Eigene Sponsoren sehen:** Die persönliche Startseite zeigt zugeordnete
   Firmen und Kontakte, aktuelle Aktivitäten, Wiedervorlagen und den
   nächsten sinnvollen Arbeitsschritt.
3. **Sponsor anlegen:** Eine neue Firma oder Person kann direkt erfasst
   werden. Der eintragende Akquisiteur wird automatisch zugeordnet.
4. **Doppelten Kontakt erkennen:** Findet LeonAid bereits eine passende
   Firma oder Person, erscheint eine Warnung mit den bisher zugeordneten
   Akquisiteuren. Erst nach Bestätigung wird eine weitere Zuordnung ergänzt.
5. **Kontaktarbeit dokumentieren:** Kontaktversuch, Ergebnis, Notiz und
   Wiedervorlage werden festgehalten.
6. **Bestellung oder Zusage erfassen:** Angebot, Menge, Preis und
   Rechnungsempfänger sind sichtbar. LeonAid übernimmt den vereinbarten Preis
   aus dem Angebot, damit er nicht versehentlich verändert werden kann.
7. **Öffentliche Reaktion mitbekommen:** Bestellt ein bereits zugeordneter
   Sponsor über die öffentliche Seite, erscheint dies unter „Neues“ bzw.
   „Aktivitäten“.
8. **Motivation und Überblick:** Die persönliche Übersichtsseite zeigt den
   eigenen Stand der Sponsorengewinnung und den Fortschritt der gesamten
   Aktion mit Wert, Einheit und verständlichem Text.

#### In Entwicklung

- Die echten Firmen- und Kontaktdaten müssen kontrolliert übernommen und
  mögliche Dubletten fachlich aufgelöst werden.
- Reale Akquisiteure müssen mit persönlichen Zugängen eingeladen und in
  moderierten Sitzungen durch ihre Kernaufgaben geführt werden.
- Rückmeldungen aus dem Pilot werden datensparsam gesammelt, priorisiert und
  einer späteren Ausbaustufe zugeordnet.
- Offline-Nutzung, Push-Nachrichten und eine Fahreransicht gehören nicht zum
  aktuellen Pilotumfang.

### 2.3 Öffentlicher Besteller oder Sponsor

#### Aktuell vorhanden

1. **Aktion öffnen:** Der Sponsor gelangt über einen einfachen Link oder
   QR-Code auf die öffentliche Krapfentaxi-Seite. Ein Benutzerkonto ist nicht
   erforderlich.
2. **Aktion verstehen:** Zweck, Zeitraum, begünstigte Organisationen,
   Aktionsziel und verfügbares Angebot werden verständlich dargestellt.
3. **Bestellung ausfüllen:** Firma oder persönliche Kontaktdaten,
   Rechnungs- und Lieferangaben sowie Anzahl der Boxen werden erfasst.
4. **Sicher absenden:** Pflichtfelder und Fehler werden verständlich
   erklärt. Mehrfaches Klicken erzeugt nicht versehentlich mehrere
   Bestellungen.
5. **Kontakt zuordnen:** Ein noch unbekannter Sponsor wird angelegt. Bei
   einem bestehenden Sponsor bleibt eine vorhandene Zuordnung zum
   Akquisiteur erhalten und löst dort eine Aktivität aus.
6. **Bestätigung erhalten:** Nach erfolgreicher Bestellung erscheint eine
   eindeutige Referenz und eine verständliche Bestätigung.

#### In Entwicklung

- Die Seite benötigt ihre endgültige öffentliche Internetadresse mit einer
  im Browser als sicher erkennbaren Verbindung.
- Datenschutzinformation, Einwilligungstexte und Kontakthinweise müssen für
  den realen Träger freigegeben werden.
- Das Formular wird erst in einem klar festgelegten Pilotzeitraum mit
  Abbruchkriterien öffentlich aktiviert.
- Mindestens ein realer öffentlicher Vorgang muss im Pilot fachlich geprüft
  werden, ohne personenbezogene Daten in öffentliche Nachweise zu übernehmen.

### 2.4 Finanzverantwortlicher oder Schatzmeister

#### Aktuell vorhanden

1. **Rechnungsjournal öffnen:** Berechtigte Personen sehen Rechnungen,
   Empfänger, Betrag, Fälligkeit, Versand- und Zahlungsstatus.
2. **Beleg prüfen:** Ausgangsrechnungen werden als übersichtlich gestaltete
   PDF-Dateien erzeugt. Sie können direkt aus dem zugehörigen Vorgang geöffnet
   und heruntergeladen werden.
3. **Unveränderlichkeit wahren:** Eine ausgestellte Rechnung und ihr PDF
   werden nicht überschrieben. Storno und Korrektur bleiben als eigener,
   nachvollziehbarer Vorgang erhalten.
4. **Versand nachvollziehen:** Erfolgreicher Versand, Wiederholungsversuche
   und mögliche Fehler sind sichtbar. Ein sicherer neuer Versandversuch ist
   vorgesehen.
5. **Zahlung erfassen:** Der aktuelle Stand unterstützt die manuelle Erfassung einer
   vollständigen Zahlung. Offene und bezahlte Fälle werden eindeutig
   unterschieden.
6. **Rechte einhalten:** Eine reine Finanz-Leserolle darf prüfen, aber keine
   Zahlung buchen oder Rechnung stornieren. Weitergehende Aktionen benötigen
   eine entsprechend berechtigte Rolle.

#### In Entwicklung

- Rechnungsaussteller, Nummernkreis, Steuerfall, Pflichttexte, Zahlungsziel
  und Bankangaben müssen mit den zuständigen Fachstellen verbindlich
  freigegeben werden.
- Es muss entschieden werden, ob für den Pilot E-Rechnungen erforderlich
  sind. Falls ja, wird der Pilot gestoppt und dafür ein eigener Milestone
  geplant.
- Rechnungen müssen über einen echten Mailanbieter an kontrollierte externe
  Postfächer zugestellt und dort geprüft werden.
- Teilzahlungen, Mahnwesen, automatische Bankzuordnung, vollständige
  Buchhaltung und Spendenbescheinigungen sind nicht Teil dieses Piloten.

### 2.5 System-Admin

#### Aktuell vorhanden

1. **Mitglieder verwalten:** Der System-Admin sieht Benutzerkonten, Status,
   Rollen, Aktionszugehörigkeiten, letzte Anmeldung und aktive Sitzungen.
   Suche und Filter helfen bei größeren Listen.
2. **Lebenszyklus der Konten steuern:** Benutzerkonten können nach frischer Anmeldung
   gesperrt, reaktiviert oder archiviert werden. Aktive Sitzungen werden beim
   Sperren sofort beendet; der letzte System-Admin kann nicht versehentlich
   entfernt werden.
3. **Rollen verwalten:** Globale Rollen und Aktionsrollen lassen sich über
   die Oberfläche vergeben und entziehen. Änderungen gelten sofort für den
   nächsten Zugriff und werden protokolliert.
4. **Einladungen betreiben:** Offene, angenommene, abgelaufene und
   widerrufene Einladungen sind sichtbar. Einladungen können kontrolliert
   erneut versendet oder widerrufen werden.
5. **Login-Adresse korrigieren:** Nur der System-Admin kann eine Änderung
   anstoßen. Die neue Adresse wird erst nach Bestätigung aktiv; alte
   Sitzungen werden anschließend beendet.
6. **Systemzustand verstehen:** Das Portal zeigt den Zustand wichtiger
   Dienste, fehlgeschlagene Hintergrundaufgaben, sichere Wiederholungen,
   Unterstützungscodes und eine datensparsame tägliche Statusübersicht.
7. **Funktionen schrittweise freigeben:** Zwei vorbereitete Funktionen können
   im Systembereich kontrolliert ein- und ausgeschaltet werden. Rechte werden
   dadurch niemals umgangen.
8. **Datenschutzvorgänge unterstützen:** Kontaktsperren, Datenauskunft und
   ein kontrollierter Weg zum Unkenntlichmachen persönlicher Daten sind vorhanden;
   aufbewahrungspflichtige Rechnungsbelege bleiben erhalten.
9. **Sichern und wiederherstellen:** Geschützte Datensicherungen,
   Wiederherstellung, Aktualisierungen, Rückkehr zur Vorversion und
   Wartungsmodus wurden mit dem Testbestand durchgespielt.

#### In Entwicklung

- Testumgebung und Produktion benötigen eigene öffentliche Internetadressen,
  sichere Verbindungen, getrennte Zugangsdaten und einen benannten
  Hosting-Verantwortlichen.
- Ein E-Mail-Dienst für den Pilotbetrieb, eine vertrauenswürdige
  Absenderadresse und
  der Umgang mit unzustellbaren Nachrichten müssen ausgewählt und praktisch
  geprüft werden.
- Die Datensicherung muss getrennt vom Produktionssystem aufbewahrt werden.
  Ein unabhängiger Betreiber muss eine Wiederherstellung ohne
  Hilfe des Projektteams durchführen.
- Systemüberwachung und Alarmwege benötigen benannte Verantwortliche. Ein
  Betreiber muss einen echten Alarm quittieren und die passende Anleitung
  ausführen.
- Veröffentlichung, Rückkehr zur Vorversion und Wartungsfenster müssen auf
  der realen Testumgebung praktisch abgenommen werden.
- Pilotzeitraum, Nutzerzahl, Unterstützungsweg, Freigabeverantwortung und
  Abbruchkriterien sind noch festzulegen.

## 3. Allgemeine Fähigkeiten der Plattform

### Aktuell vorhanden

#### Eine Plattform mit drei passenden Zugängen

- Das interne Portal bündelt Administration, Aktionen, Bestellungen,
  Rechnungen, Mitglieder, Datenschutz und Betrieb.
- Die mobile Akquisiteur-App nutzt dieselben Regeln und Daten, ist aber auf
  die Arbeit unterwegs zugeschnitten.
- Öffentliche Aktionsseiten bleiben schlank und benötigen keine Anmeldung.
- Ein zentrales Kontakt- und Firmenverzeichnis hält Stammdaten zusammen.
  Mitglieder
  arbeiten im Regelfall über LeonAid und erhalten dadurch nur die Daten, die
  sie für ihre Rolle und Aktion sehen dürfen.

#### Flexible Charity-Aktionen statt einer Krapfentaxi-Sonderlösung

- Aktion, Zeitraum, Ziel, Begünstigte und öffentliche Veröffentlichung
  bilden einen gemeinsamen Kern.
- Zusätzliche Bausteine wie Angebote, Bestellung, Rechnung oder später
  Auslieferung werden je Aktion zugeschaltet.
- Vorlagen sind versioniert. Eine neue Vorlage verändert keine bereits
  archivierte Aktion.
- Krapfentaxi ist der erste vollständig umgesetzte Anwendungsfall. Das
  Grundmodell ist auf weitere Aktionsarten vorbereitet.

#### Rollen, Datenschutz und Nachvollziehbarkeit

- Rechte gelten global oder nur für eine bestimmte Charity-Aktion.
- LeonAid prüft die Berechtigung bei jedem Zugriff; das bloße Ausblenden eines Menüpunkts
  ist kein Sicherheitsmechanismus.
- Kritische Änderungen verlangen eine frische Anmeldung und werden
  protokolliert.
- Einwilligungen, Kontaktsperren, Datenauskunft und das kontrollierte
  Unkenntlichmachen persönlicher Daten sind grundsätzlich vorgesehen.
- Öffentliche Test- und Betriebsnachweise werden so erzeugt, dass keine
  echten Personen-, Kontakt-, Rechnungs- oder Zugangsdaten hineingelangen.

#### Kontakte, Bestellungen und Aktivitäten

- Firmen und Personen werden zentral geführt und mit Charity-Aktionen sowie
  einem oder mehreren Akquisiteuren verbunden.
- Interne Zusagen und öffentliche Bestellungen verwenden dasselbe
  Bestellmodell.
- Mengen, Preise, Boxen und Stückzahlen bleiben nachvollziehbar. LeonAid
  übernimmt den Preis aus dem jeweils gültigen Angebot.
- Ereignisse wie eine öffentliche Bestellung erscheinen bei den zuständigen
  Akquisiteuren und Charity-Admins.

#### Rechnungen und Belege

- LeonAid erzeugt Ausgangsrechnungen als übersichtlich gestaltete
  PDF-Dateien.
- Erzeugte Dokumente werden sicher gespeichert und mit Firma oder Kontakt,
  Aktion, Bestellung und Rechnung verknüpft.
- Rechnungsversand, Versandprotokoll, manuelle Vollzahlung und Storno sind
  abgebildet.
- Belege werden geschützt abgelegt und bleiben nur für berechtigte Personen
  im zugehörigen Vorgang abrufbar.

#### Gute Bedienbarkeit auf Desktop und Smartphone

- Gemeinsame Navigation mit einklappbarer Seitenleiste und klarer
  Rollen-/Aktionsanzeige.
- Heller Modus, dunkler Modus oder automatische Systemeinstellung.
- Verständliche Hilfetexte, Fehlerzustände, Bestätigungen und nächste
  Schritte.
- Kritische Wege wurden auf Smartphone und Desktop, mit Tastatur,
  Vergrößerung und automatischen Barrierefreiheitsprüfungen getestet.

#### Kontrollierter Betrieb

- Die Plattform wird als abgestimmtes Gesamtpaket bereitgestellt. Optionale
  Bereiche können bei Bedarf getrennt zugeschaltet werden.
- Aktualisierungen der eingesetzten Bausteine erfolgen kontrolliert auf
  vorher geprüfte Versionen.
- Die Plattform überwacht, ob die wichtigen Bereiche nicht nur gestartet,
  sondern tatsächlich arbeitsbereit sind.
- Datensicherung, Wiederherstellung, Aktualisierung, Rückkehr zur Vorversion,
  Wartungsmodus, Zustandsanzeigen, Alarmregeln und sichere Wiederholungen
  wurden mit dem Testbestand erfolgreich durchgespielt.
- Der vollständige Krapfentaxi-Weg wird regelmäßig automatisch in mehreren
  verbreiteten Browsern wiederholt. Dabei wird das Zusammenspiel von
  Kontaktverwaltung, Bestellungen, Belegen und E-Mail geprüft.

### In Entwicklung

#### Vom Demonstrationsbetrieb zum echten Pilot für einen Club

- Aufbau einer getrennten Test- und Produktionsumgebung für genau einen
  Club bzw. Träger.
- Festlegung der öffentlichen Internetadresse, des Betriebsorts, der
  geschützten Zugangsdaten und der verantwortlichen Personen.
- Prüfung der sicheren Verbindung unter der späteren öffentlichen
  Testadresse.
- Im echten Betrieb dürfen nur ausdrücklich freigegebene Versionen
  veröffentlicht werden.

#### Produktiver Mailbetrieb

- Auswahl und Freigabe eines E-Mail-Dienstes für den Pilotbetrieb.
- Einrichtung einer vertrauenswürdigen Absenderadresse mit den notwendigen
  Schutzmaßnahmen gegen Missbrauch.
- Prüfung von Login-Code, Einladung und Rechnung an kontrollierten externen
  Postfächern bei mindestens zwei unterschiedlichen E-Mail-Anbietern.
- Festlegung, wie unzustellbare Nachrichten und Beschwerden behandelt
  werden.

#### Kontrollierte Übernahme echter Bestandsdaten

- Ablage der noch zu liefernden Excel-Datei in einem geschützten privaten
  Bereich.
- Dokumentation von Zweck, Berechtigung und Herkunft.
- Analyse der echten Spalten, Formate, Dubletten und stabilen Schlüssel.
- Zuerst ein Probelauf ohne Änderungen, anschließend Konfliktauflösung und
  Vier-Augen-Freigabe.
- Übernahme in die Testumgebung, Wiederholungs- und Wiederherstellungsprüfung
  und erst danach eine kontrollierte Übernahme in das echte System.

#### Verbindliche Fachkonfiguration

- Bestätigung von Träger, Rechnungsaussteller und Bank-/Kontaktdaten.
- Entscheidung zu Steuerbehandlung, Pflichtangaben und E-Rechnung.
- Freigabe von Datenschutztexten, Rechtsgrundlagen, Sperr-, Lösch- und
  Aufbewahrungsfristen.
- Inhaltliche Abnahme eines echten Rechnungsbelegs aus der Testumgebung durch
  die zuständige Fachperson.

#### Betrieb mit echten Verantwortlichen

- Externes, getrennt geschütztes Sicherungsziel und regelmäßige
  Wiederherstellung durch einen unabhängigen Betreiber.
- Aktiver Alarmkanal außerhalb des LeonAid-Mailwegs, benannte
  Ansprechpartner und geübte Eskalation.
- Praktische Veröffentlichungs-, Rückkehr-, Störungs- und
  Unterstützungsübungen anhand der Betriebsanleitungen.
- Täglicher datensparsamer Betriebsbericht während des Pilotzeitraums.

#### Pilotdurchführung und Abnahme

- Produktionsnahe Generalprobe mit echten Anbietern und einem rechtmäßig
  verwendbaren, kontrollierten Pilotdatensatz.
- Einführung eines kleinen, klar benannten Nutzerkreises mit individuellen
  Benutzerkonten.
- Moderierte Nutzung durch Charity-Admin, Akquisiteur, Finanzen und
  System-Admin sowie eine praktische Prüfung mit Vorlesesoftware.
- Begrenzter Pilotbetrieb mit Start, Ende, Nutzerzahl, Stopregeln und
  Unterstützungsweg.
- Fachliche Bestätigung mindestens eines internen und eines öffentlichen
  realen Vorgangs.
- Abschlussentscheidung: zuerst Krapfentaxi-Auslieferung vertiefen, den
  Betrieb weiter härten oder mit der Lions-Open-Erkundung beginnen.

## 4. Bewusst nicht Teil des aktuellen Piloten

Die folgenden Themen sind keine versteckten Zusagen und werden nicht als
„fast fertig“ dargestellt:

- Tourenplanung, Fahrerdisposition, Google-Maps-Navigation, Offline-Abgleich
  und Push-Nachrichten;
- Lions Open und Weihnachtsmarkt als produktive Aktionsarten;
- ein eigener Bereich für Newsletter und Kampagnenkommunikation;
- allgemeiner Baukasten für Formulare, Abläufe oder öffentliche Seiten;
- vollständige Buchhaltung, Bankanbindung, automatische Zahlungszuordnung,
  Teilzahlungen, Mahnwesen und Spendenbescheinigungen;
- allgemeines Dokumentenmanagement mit freiem Upload, Volltextsuche und
  beliebiger Versionierung;
- mehrere Clubs innerhalb derselben Installation, Hochverfügbarkeit oder
  Betrieb über mehrere Regionen;
- weitere Anmeldearten über andere Anbieter sowie öffentliche
  Selbstregistrierung.

Diese Grenzen schützen den Pilot davor, zu viele Risiken gleichzeitig zu
öffnen. Nach einem erfolgreichen Krapfentaxi-Pilot können die nächsten
Funktionen anhand realer Erfahrungen priorisiert werden.

## 5. Zusammenfassung für Entscheider und Beteiligte

LeonAid ist heute ein funktionsfähiger, durchgängiger
Krapfentaxi-Prototyp. Die
wichtigsten Wege für Charity-Admin, Akquisiteur, öffentlichen Sponsor,
Finanzen und System-Admin sind vorhanden. Kontakte, Bestellungen,
Aktivitäten, Rechnungs-PDFs, Versandstatus, Zahlung, Rollen, Dokumente und
Übersichtsseiten greifen ineinander. Auch die Grundlage für sicheren
Betrieb, Datenschutz und Wiederherstellung ist aufgebaut und mit
künstlichen Testdaten geprüft.

Der nächste Schritt ist keine große Neuentwicklung des fachlichen Kerns,
sondern die kontrollierte Überführung in einen echten Pilotbetrieb für einen
Club. Dazu müssen reale Verantwortliche und Anbieter festgelegt, echte
Bestandsdaten geschützt übernommen, rechtliche und steuerliche Entscheidungen
getroffen und sämtliche Abläufe in einer Testumgebung und anschließend mit
einem kleinen Pilotkreis praktisch bestätigt werden.

Erst nach diesen Nachweisen wird aus dem erfolgreichen Prototyp eine
freigegebene Pilotplattform.

## 6. Projektinterne Grundlagen

Diese Übersicht wurde aus den folgenden verbindlichen Projektständen
abgeleitet:

- [`PERSONAS.md`](../PERSONAS.md) - Personas, Rollen und Zugriffsgrenzen;
- [Krapfentaxi-Abnahme](leonaid-poc/ACCEPTANCE.md) - vollständig abgenommener
  Prototyp;
- [Bekannte Grenzen](leonaid-poc/KNOWN-LIMITS.md) - bewusst
  verschobene Funktionen;
- [Pilotplan](leonaid-pilot/PLAN.md) - Weg vom Prototyp zum begrenzten
  Pilotbetrieb für einen Club;
- [Offene Pilotentscheidungen](leonaid-pilot/DECISIONS.md) - noch
  offene Träger-, Steuer-, Datenschutz- und Betriebsentscheidungen;
- [Produkt- und Architekturkonzept](produkt-und-architekturvorschlag.md) -
  Rahmen über Krapfentaxi hinaus.

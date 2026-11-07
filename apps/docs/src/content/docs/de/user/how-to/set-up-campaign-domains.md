---
title: Domains für Aktionen einrichten
description: Eine Aktion unter einer eigenen Domain oder Subdomain zeigen, Folgeaktionen übernehmen lassen und Domains wieder entfernen.
docId: DOC-P048
audience: [user]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: e61f18a07a9f9aaa59f7e91e19008a6c185dd136
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** System-Admin. Domains kosten Geld und betreffen den ganzen Club,
deshalb verwaltet nur die System-Administration sie. Charity-Admins sehen die
Adressen ihrer Aktion, ändern sie aber nicht.

Eine Aktion kann unter einer eigenen Domain (`krapfentaxi.org`) oder einer
Subdomain des Clubs (`weihnachtsmarkt.example.org`) laufen. Die Verwaltung
bleibt auf dem Verwaltungshost. Jede Domain zeigt nur die Kampagnenseiten der
Aktionen, die an sie gebunden sind.

## Domain eintragen

1. Öffne **System** › **Domains**.
2. Trage unter **Domain** nur den Namen ein, ohne `https://` und ohne Pfad,
   und wähle **Domain hinzufügen**. Großbuchstaben und Umlaute sind erlaubt;
   LeonAid speichert die Schreibweise, die DNS verwendet.
3. Lege beim Registrar oder DNS-Anbieter den Eintrag an, den die Domain-Karte
   nennt: für eine Subdomain einen `CNAME` auf den Host des Clubs, für eine
   eigene Domain `A` und `AAAA` auf die Adressen dieses Servers.
   Weiterleitungsangebote des Registrars funktionieren nicht.

Der Verwaltungshost, der öffentliche Host und dessen Zusatznamen lassen sich
nicht eintragen, ebenso keine Namen unterhalb des Verwaltungshosts.

## Domain prüfen

1. Warte, bis der DNS-Eintrag sichtbar ist (oft Minuten, manchmal Stunden).
2. Wähle auf der Domain-Karte **Prüfen**.

LeonAid ruft die Prüfadresse der Karte über jede öffentliche Adresse der
Domain auf. Antwortet überall dieser Server, steht die Domain auf **Geprüft**.
Beim ersten Aufruf über HTTPS holt der Server ein Zertifikat von Let's
Encrypt; danach steht sie auf **Aktiv**. Steht sie noch auf **Geprüft**,
prüfe nach einer Minute erneut. Erst eine geprüfte Domain erhält ein
Zertifikat; ein Neustart ist nicht nötig.

LeonAid prüft aktive Domains täglich. Schlägt die Prüfung drei Mal über
mindestens 72 Stunden fehl, wird die Domain **Abgeschaltet** und erhält kein
Zertifikat mehr. **System** › **Betrieb** zeigt solche Domains unter
**Domains für Aktionen**. Wird die Prüfung wieder grün, wird die Domain
wieder aktiv; ihre Ausgaben bleiben in der Zeit gebunden.

## Aktion binden

1. Wähle auf der Domain-Karte **Aktion binden**.
2. Wähle die **Aktion**. Der **Pfad der Ausgabe** ist optional; leer bekommt
   die Ausgabe das Jahr ihres Publikationsbeginns, zum Beispiel `2025`.
3. Lass **Diese Ausgabe unter „/“ zeigen** an, wenn die Aktion die Startseite
   der Domain sein soll.
4. Bestätige mit **Binden**.

Die Domain zeigt nur Kampagnenseiten aus dem CMS. Hat die Aktion keine
veröffentlichte Kampagnenseite, warnt der Dialog.

Jede Ausgabe ist dauerhaft unter `https://<domain>/<pfad>/` erreichbar. Die
Startseite `/` zeigt die Ausgabe, die **aktuell auf /** steht, solange sie
läuft. Nach dem Ende leitet `/` auf die Archivseite der Ausgabe weiter.

## Was Besucher sehen

- `https://<domain>/` zeigt die laufende Ausgabe. Ist sie beendet, leitet `/`
  auf ihre Archivseite weiter, etwa `/2025/`. Die Archivseite zeigt die
  Kampagnenseite ohne Bestellformular.
- Hat die Domain mehrere Ausgaben, verlinkt der Seitenfuß **Frühere
  Ausgaben**; `/archive/` listet alle Ausgaben.
- Die bisherigen Adressen der Aktion auf dem öffentlichen Host, ihre Aliase
  und `/campaigns/<slug>/` leiten auf die Domain weiter. Gedruckte QR-Codes
  funktionieren also weiter.
- Impressum und Datenschutz sind auf jeder Domain erreichbar. Jede Domain hat
  eigene `robots.txt` und `sitemap.xml`.
- **Live-Ansicht** im Microsite-Editor öffnet die Seite auf ihrer Domain.

## Domain an eine Folgeaktion übergeben

Für wiederkehrende Aktionen, etwa Lions Open 2025 und 2026:

1. Wähle **Domain an Folgeaktion übergeben**.
2. Wähle die Folgeaktion und bei Bedarf ihren Pfad.
3. Prüfe die Vorschau: Die Folgeaktion übernimmt `/` ab ihrem
   Publikationsbeginn. Die bisherige Ausgabe bleibt unter ihrem Pfad
   erreichbar; Aliase und verschickte Bestellbestätigungen zeigen dorthin.
4. Bestätige mit **Übergeben**.

Laufen beide Ausgaben gleichzeitig, nimmt die bisherige unter ihrem Pfad
weiter Bestellungen an.

## Weitere Einstellungen

- **Pfad ändern:** Der alte Pfad leitet danach dauerhaft auf den neuen. Er
  steht unter **Frühere Pfade**.
- **Als Weiterleitung nutzen:** Eine Domain ohne Ausgaben, etwa
  `www.krapfentaxi.org`, leitet als Ganzes auf eine andere Domain weiter. Der
  Pfad bleibt erhalten.
- **Als Hauptadresse:** Läuft eine Aktion auf zwei Domains, bestimmt die
  Hauptadresse den Link in Suchmaschinen und Mails.
- **Lösen:** Die Ausgabe verschwindet von der Domain; ihr Pfad leitet auf die
  nächste öffentliche Adresse der Aktion. Ist es die einzige Ausgabe, zeigt
  `/` danach eine Fehlerseite; der Dialog fragt das ab.

## Domain entfernen

1. Wähle **Domain entfernen**.
2. Die Vorschau zeigt für jede Ausgabe ihre neue Adresse, oder „nicht mehr
   öffentlich erreichbar“.
3. Bestätige mit **Entfernen**.

Die Domain wird abgeschaltet und erhält kein Zertifikat mehr. Alte Links auf
diese Domain funktionieren danach nicht mehr; Aliase und Adressen auf dem
öffentlichen Host bleiben. Leitet eine andere Domain noch hierher weiter,
entferne oder ändere zuerst diese. Eine entfernte Domain kannst du später neu
eintragen; sie wird dann erneut geprüft.

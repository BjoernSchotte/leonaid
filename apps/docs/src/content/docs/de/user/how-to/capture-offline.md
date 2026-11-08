---
title: Offline erfassen
description: Kontakte, Wiedervorlagen, Bestellungen und neue Sponsoren in der Akquise-App ohne Netz erfassen und später automatisch senden.
docId: DOC-P050
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 0a840abef544ca6c79841ab9e4acd677567159f1
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Akquisiteur einer Aktion in der Akquise-App. Die Offline-Erfassung
gibt es nur, wenn die System-Administration das Feature-Flag
**Offline-Erfassung in der Akquise-App** eingeschaltet hat. Ohne Flag zeigt die
App offline nur, was schon geöffnet ist, und speichert nichts. Das Flag kommt
erst an, wenn der aktive Datenschutzhinweis für Mitglieder den Abschnitt
„Speicherung auf deinem Gerät“ enthält (siehe
[Impressum und Datenschutzerklärung pflegen](../maintain-legal-pages/)).

## Vorbereiten

1. Öffne die Akquise-App einmal mit Verbindung und melde dich an.
2. Warte, bis deine Sponsorenliste geladen ist. Die App legt eine
   verschlüsselte Kopie deiner eigenen Sponsoren und der Bestellangaben
   (Angebote, Preise, Lieferfenster) auf dem Gerät ab und hält sie aktuell,
   solange du online bist.

Ohne Verbindung startet die App dann aus dieser Kopie. Sie zeigt sie bis zu
7 Tage nach dem letzten Abgleich. Ist sie älter, erscheint **Deine
Sponsorenliste ist älter als 7 Tage. Geh online, um sie zu aktualisieren.**,
und du kannst offline nichts erfassen.

## Offline erfassen

Offline steht oben **Du bist offline. Neue Kontakte, Wiedervorlagen und
Bestellungen speichert LeonAid auf diesem Gerät und sendet sie, sobald du
wieder online bist.**

- **Kontakt und Wiedervorlage:** Öffne den Sponsor, wähle **Kontakt erfassen**
  und speichere wie gewohnt. Die App meldet **Kontakt gespeichert. Wird
  gesendet, sobald du wieder online bist.** Gesperrte Kontaktwege kannst du
  auch offline nicht wählen.
- **Bestellung:** Wähle beim Sponsor **Bestellung erfassen**. Unter dem
  Betrag steht, von wann der Preis stammt. Hat er sich bis zum Senden
  geändert, fragt dich die App, bevor die Bestellung gespeichert wird. Online
  fragt sie das gleich auf dem Formular, ebenso bei einem inzwischen
  ausgebuchten Lieferfenster. Nach dem Speichern siehst du **Bestellung
  gespeichert**.
- **Neuer Sponsor:** Unter **Neu** speicherst du offline einen Entwurf (ohne
  Straße). Zu diesem Entwurf kannst du gleich einen Kontakt erfassen; er
  zeigt **Wartet auf den Entwurf**. Die CRM-Prüfung läuft erst online: Die
  Warteschlange zeigt **Neuer Sponsor … wartet auf deine Prüfung**. **Jetzt
  prüfen** öffnet das gewohnte Formular mit deinen Angaben; ergänze bei
  Bedarf die Straße und wähle **Im CRM prüfen**. Danach sendet die App den
  Kontakt zu diesem Sponsor.

Auch online gehen deine Kontakte und Bestellungen über die Warteschlange. Die
App sendet sie sofort; geht eine Antwort verloren, sendet sie denselben
Eintrag noch einmal, und LeonAid speichert ihn trotzdem nur einmal.

## Die Warteschlange

Das Netz-Symbol oben rechts zeigt, was wartet. Tippe darauf, um die
**Warteschlange** zu öffnen.

| Anzeige                          | Bedeutung                                                        |
| -------------------------------- | ---------------------------------------------------------------- |
| **Wartet auf Verbindung**        | Wird gesendet, sobald du online bist.                            |
| **Wird gesendet …**              | Die App sendet gerade.                                           |
| **Gesendet**                     | LeonAid hat den Eintrag (bis du die App schließt).               |
| **Braucht deine Entscheidung**   | LeonAid hat den Eintrag nicht so angenommen; du wählst, wie es weitergeht. |
| **Konnte nicht gesendet werden** | Mehrere Versuche sind gescheitert; **Erneut versuchen** oder **Verwerfen**. |
| **Abgelaufen**                   | Älter als 14 Tage; wird zwei Tage später gelöscht.               |
| **Nicht mehr möglich**           | Du arbeitest nicht mehr in dieser Aktion; wird zwei Tage später gelöscht. |

Die App sendet beim Öffnen, wenn du zu ihr zurückkehrst, wenn die Verbindung
zurückkommt und mit **Jetzt senden**. Auf dem iPhone sendet sie nur, solange
die App geöffnet ist.

## Entscheidungen

| Was die App meldet                                         | Deine Wahl                                                                        |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Kontakt gespeichert, Wiedervorlage nicht übernommen        | **Meine Wiedervorlage übernehmen** oder **Die andere Wiedervorlage behalten**     |
| Kontakt gespeichert, Status nicht übernommen               | **Meinen Stand übernehmen** oder **Den anderen Stand behalten**                   |
| Der Sponsor möchte auf diesem Weg nicht kontaktiert werden | **Als Besuch speichern** oder **Verwerfen**                                       |
| Der Sponsor ist dir nicht mehr zugeordnet                  | **Notiz kopieren** oder **Verwerfen**                                             |
| Das Lieferfenster ist inzwischen ausgebucht                | **Trotzdem eintragen**, **Anderes Fenster wählen**, **Als Entwurf speichern** oder **Verwerfen** |
| Das Lieferfenster gibt es nicht mehr                       | **Anderes Fenster wählen**, **Als Entwurf speichern** oder **Verwerfen**          |
| Der Preis hat sich geändert                                | **Neuen Preis übernehmen** oder **Verwerfen**                                     |
| Die Bestellung braucht jetzt Lieferadresse und Fenster     | **Ergänzen**, **Als Entwurf speichern** oder **Verwerfen**                        |
| Das Angebot ist nicht mehr bestellbar oder die Aktion nimmt keine Bestellungen mehr an | **Verwerfen**                                           |
| Die Uhrzeit deines Geräts stimmt nicht                     | Uhrzeit prüfen, dann **Verwerfen** und neu erfassen                               |

## Abmelden und Gerät wechseln

Beim Abmelden, in der Akquise-App oder im Verwaltungsbereich, löscht die App
alles, was sie auf dem Gerät gespeichert hat.
Warten noch Einträge, fragt sie vorher: **Erst senden** (sendet und öffnet
die Warteschlange; im Verwaltungsbereich **Zur Akquise-App**), **Trotzdem
abmelden** (löscht die Einträge) oder **Abbrechen**. Meldet sich auf dem Gerät eine andere Person
an, löscht die App deine Daten ohne Rückfrage, bevor sie deren Arbeitsbereich
zeigt.

## Grenzen

- Offline gehen nur Sponsoren, Wiedervorlagen, Kontakte und Bestellungen. Die
  Startseite mit dem Aktionsstand, Aufgaben, Material, Wissen, Postfach und
  das Lieferboard brauchen eine Verbindung.
- Straßenadressen deiner Sponsoren liegen nicht auf dem Gerät. Für eine
  Bestellung gibst du die Adresse ein.
- Zwei Geräte wissen nichts voneinander: Erfasst du denselben Kontakt auf
  beiden, steht er zweimal im Verlauf.

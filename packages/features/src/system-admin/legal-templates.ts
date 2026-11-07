/**
 * Default texts for the public privacy page (/datenschutz).
 *
 * LEGAL REVIEW PENDING: Björn Schotte has not reviewed these templates yet.
 * They describe only what LeonAid itself does; everything the club must
 * decide or know (legal bases, service providers, retention in plain words,
 * supervisory authority) is a [[...]] placeholder. A placeholder blocks
 * production activation (`template_placeholder_open`), and every text goes
 * through the four-eyes draft/approval flow before it is published.
 *
 * Format: blocks separated by an empty line; "## " starts a heading and
 * "- " a list item (apps/public/src/lib/legal-text.ts renders it).
 */

export const PRIVACY_POLICY_TEMPLATE = `## Verantwortlicher

Verantwortlich für die Verarbeitung personenbezogener Daten auf diesen Seiten ist der im Impressum genannte Träger. Für Fragen zum Datenschutz erreichen Sie uns über die unten genannte Datenschutz-Kontaktadresse.

[[Falls der Verein eine Person für den Datenschutz benannt hat: Name und Kontakt eintragen. Sonst diesen Absatz löschen.]]

## Aufruf der Seiten

Beim Aufruf dieser Seiten verarbeitet der Server technisch notwendige Daten: IP-Adresse, Zeitpunkt, aufgerufene Adresse und Browserkennung. Sie werden benötigt, um die Seiten auszuliefern und vor Missbrauch zu schützen. LeonAid setzt keine Analyse- oder Marketing-Cookies.

[[Hosting-Anbieter, Speicherdauer der Server-Protokolle und Rechtsgrundlage eintragen.]]

[[Eingebundene Dienste Dritter prüfen, z. B. eine Kartendarstellung auf Aktionsseiten, und hier benennen.]]

## Bestellungen und Anfragen über Aktionsseiten

Wenn Sie über eine Aktionsseite bestellen oder eine Anfrage senden, verarbeiten wir die Angaben aus dem Formular, um Ihre Bestellung oder Anfrage zu bearbeiten. Zweck, Rechtsgrundlage und Kontakt stehen zusätzlich direkt am Formular.

[[Empfänger der Daten eintragen, z. B. Steuerberatung, Bank oder Lieferdienst.]]

## Umfragen

Wenn Sie an einer Umfrage teilnehmen, verarbeiten wir Ihre Antworten für den Zweck, der in der Umfrage genannt ist.

[[Zweck, Rechtsgrundlage und Speicherdauer der Umfragen eintragen.]]

## E-Mails

LeonAid versendet E-Mails für Anmelde-Links, Einladungen, Bestellbestätigungen und Rechnungen.

[[E-Mail-Versanddienstleister eintragen.]]

## Speicherdauer

Wir speichern personenbezogene Daten nur so lange, wie es für den jeweiligen Zweck nötig ist oder gesetzliche Aufbewahrungspflichten bestehen.

[[Aufbewahrungsfristen aus „Aufbewahrungsfristen“ in verständlichen Worten eintragen.]]

## Ihre Rechte

Sie haben nach der Datenschutz-Grundverordnung das Recht auf Auskunft (Art. 15), Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit (Art. 20) und Widerspruch (Art. 21). Eine Einwilligung können Sie jederzeit mit Wirkung für die Zukunft widerrufen. Sie können sich außerdem bei einer Datenschutz-Aufsichtsbehörde beschweren (Art. 77).

[[Zuständige Aufsichtsbehörde mit Anschrift eintragen.]]`;

/**
 * Members' privacy notice, addressed in "Du" like the PWA and member pages.
 * The section "Speicherung auf deinem Gerät" is decision D8 of
 * specs/pwa-offline-queue/PLAN.md (§8.2–§8.5, §14): it describes the
 * offline queue and read cache of the acquisition app.
 */
export const MEMBER_PRIVACY_NOTICE_TEMPLATE = `## Mitgliederbereich und Akquise-App

Als Mitglied meldest du dich mit deiner E-Mail-Adresse an. LeonAid verarbeitet deinen Namen, deine E-Mail-Adresse, deine Rollen in den Aktionen und das, was du in LeonAid erfasst, zum Beispiel Kontaktversuche, Bestellungen und Aufgaben. So kann der Club seine Aktionen planen, durchführen und abrechnen. Die Anmeldung setzt ein technisch notwendiges Sitzungs-Cookie.

[[Rechtsgrundlage für die Verarbeitung von Mitgliederdaten und Speicherdauer nach dem Austritt eintragen.]]

## Speicherung auf deinem Gerät

[[Diesen Abschnitt nur behalten, wenn die Offline-Erfassung der Akquise-App aktiv ist; sonst den ganzen Abschnitt löschen. Danach diese Zeile löschen.]]

Damit du Kontaktversuche und Bestellungen auch ohne Netz erfassen kannst, speichert die Akquise-App Daten auf deinem Gerät:

- die Liste deiner eigenen zugewiesenen Sponsoren mit Name, Ort, Status und nächstem Schritt sowie den Kontaktdaten Ansprechperson, Telefonnummer und E-Mail-Adresse;
- Einträge, die noch nicht gesendet sind, zum Beispiel Notizen, Kontaktversuche und Bestellungen mit Lieferadresse und Kontakt.

Nicht auf deinem Gerät gespeichert werden die Straßenadressen der Sponsoren (außer der Lieferadresse einer Bestellung, die noch nicht gesendet ist), Rechnungsdaten, Bestellungen anderer Mitglieder und Daten der Auslieferung.

Die Daten liegen verschlüsselt im Speicher des Browsers. Der Schlüssel kann das Gerät nicht verlassen. Zusätzlich schützt die Gerätesperre deines Telefons.

Die App sendet Einträge, sobald du wieder online bist, und löscht sie danach sofort vom Gerät. Ein Eintrag, der 14 Tage lang nicht gesendet werden konnte, gilt als abgelaufen und wird zwei Tage später gelöscht. Die Sponsorenliste zeigt die App nach 7 Tagen nicht mehr an und löscht sie nach 14 Tagen. Endet deine Mitarbeit in einer Aktion oder schaltet der Club die Akquise dort ab, kann die App deren Einträge nicht mehr senden: Du kannst sie noch lesen und verwerfen, nach zwei Tagen löscht die App sie.

Wenn du dich abmeldest, löscht die App alle Daten, die sie auf dem Gerät gespeichert hat. Meldet sich auf dem Gerät eine andere Person an, löscht die App deine Daten, bevor sie deren Arbeitsbereich zeigt. Wenn du die Website-Daten im Browser löschst oder die App entfernst, sind die Daten ebenfalls gelöscht.`;

/**
 * Default texts for the public privacy page (/datenschutz) and, at the end
 * of the file, proposals for the donation documents.
 *
 * LEGAL REVIEW PENDING: Björn Schotte has not reviewed these templates yet.
 * They describe only what LeonAid itself does; everything the club must
 * decide or know (legal bases, service providers, retention in plain words,
 * supervisory authority) is a [[...]] placeholder. A placeholder blocks
 * production activation (`template_placeholder_open`), and every text goes
 * through the four-eyes draft/approval flow before it is published.
 *
 * The section "Bestellungen, die ein Mitglied für Sie erfasst" is P1 of
 * specs/mails-documents-donations-push/PLAN.md (§13, Appendix A.1): the
 * legal basis for mails to buyers whose order a member entered. LEGAL
 * REVIEW PENDING: Björn Schotte signs it before a club switches these mails
 * on in production ("E-Mails an Käufer" in the action settings).
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

## Bestellungen, die ein Mitglied für Sie erfasst

Nimmt ein Mitglied unseres Clubs Ihre Bestellung persönlich oder am Telefon auf, speichern wir Ihren Namen, Ihre Liefer- und Rechnungsanschrift und Ihre E-Mail-Adresse, wenn Sie sie nennen oder sie uns aus einer früheren Bestellung vorliegt. An diese Adresse senden wir die Bestellbestätigung, am Liefertag einen Hinweis auf das Lieferfenster und, falls die Bestellung storniert wird, eine Stornobestätigung. Rechtsgrundlage ist die Erfüllung des Vertrags mit Ihnen (Art. 6 Abs. 1 Buchst. b DSGVO). Werbung senden wir an diese Adresse nicht.

## Umfragen

Wenn Sie an einer Umfrage teilnehmen, verarbeiten wir Ihre Antworten für den Zweck, der in der Umfrage genannt ist.

[[Zweck, Rechtsgrundlage und Speicherdauer der Umfragen eintragen.]]

## E-Mails

LeonAid versendet E-Mails für Anmelde-Links, Einladungen, Bestellbestätigungen, Hinweise am Liefertag, Stornobestätigungen und Rechnungen.

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
 * offline queue, read cache and identity summary of the acquisition app.
 * Text proposed by Claude Code for Björn Schotte's review; the legal
 * configuration's four-eyes flow activates it.
 *
 * The section "Benachrichtigungen auf deinem Gerät" is the proposal of
 * specs/mails-documents-donations-push/PLAN.md, Appendix A.4 (P4), in the
 * "Du" of this notice. Core stores the address and the two keys, nothing
 * about the browser. LEGAL REVIEW PENDING: the flag `pwa.push` may
 * be switched on only once the active notice carries this section.
 */
export const MEMBER_PRIVACY_NOTICE_TEMPLATE = `## Mitgliederbereich und Akquise-App

Als Mitglied meldest du dich mit deiner E-Mail-Adresse an. LeonAid verarbeitet deinen Namen, deine E-Mail-Adresse, deine Rollen in den Aktionen und das, was du in LeonAid erfasst, zum Beispiel Kontaktversuche, Bestellungen und Aufgaben. So kann der Club seine Aktionen planen, durchführen und abrechnen. Die Anmeldung setzt ein technisch notwendiges Sitzungs-Cookie.

[[Rechtsgrundlage für die Verarbeitung von Mitgliederdaten und Speicherdauer nach dem Austritt eintragen.]]

## Speicherung auf deinem Gerät

[[Diesen Abschnitt nur behalten, wenn die Offline-Erfassung der Akquise-App aktiv ist; sonst den ganzen Abschnitt löschen. Danach diese Zeile löschen.]]

Damit du Kontaktversuche und Bestellungen auch ohne Netz erfassen kannst, speichert die Akquise-App Daten auf deinem Gerät:

- eine Kurzform deiner eigenen Anmeldung, damit die App auch ohne Netz startet: dein Name, deine Aktionen und deine Rollen (nicht deine E-Mail-Adresse);
- die Liste deiner eigenen zugewiesenen Sponsoren mit Name, Ort, Status und nächstem Schritt sowie den Kontaktdaten Ansprechperson, Telefonnummer und E-Mail-Adresse;
- Einträge, die noch nicht gesendet sind, zum Beispiel Notizen, Kontaktversuche, neue Sponsoren als Entwurf mit Name, Ansprechperson, E-Mail-Adresse, PLZ und Ort (ohne Straße) und Bestellungen mit Rechnungsadresse, Lieferadresse und Kontakt.

Nicht auf deinem Gerät gespeichert werden die Straßenadressen der Sponsoren (außer der Rechnungs- und Lieferadresse einer Bestellung, die noch nicht gesendet ist), Rechnungen, Bestellungen anderer Mitglieder und Daten der Auslieferung. Ergänzt du bei der Prüfung eines Entwurfs im CRM die Straße, bleibt sie verschlüsselt auf dem Gerät, bis die Prüfung abgeschlossen ist, längstens 14 Tage.

Die Daten liegen nur auf diesem Gerät, verschlüsselt im Speicher des Browsers. Der Schlüssel kann das Gerät nicht verlassen. Zusätzlich schützt die Gerätesperre deines Telefons.

Die App sendet Einträge, sobald du wieder online bist, und löscht sie danach sofort vom Gerät; das gilt auch für die Rechnungs- und Lieferadresse einer Bestellung. Ein Eintrag, der 14 Tage lang nicht gesendet werden konnte, gilt als abgelaufen und wird zwei Tage später gelöscht. Die Sponsorenliste zeigt die App nach 7 Tagen nicht mehr an und löscht sie nach 14 Tagen. Endet deine Mitarbeit in einer Aktion oder schaltet der Club die Akquise dort ab, kann die App deren Einträge nicht mehr senden: Du kannst sie noch lesen und verwerfen; bis dahin bleiben sie auf dem Gerät.

Wenn du dich abmeldest, in der Akquise-App oder im Verwaltungsbereich, löscht die App alle Daten, die sie auf dem Gerät gespeichert hat. Endet deine Sitzung, löscht sie die Kurzform deiner Anmeldung und die Sponsorenliste; noch nicht gesendete Einträge bleiben, bis du dich wieder anmeldest, längstens bis zu den oben genannten Fristen. Meldet sich auf dem Gerät eine andere Person an, löscht die App deine Daten, bevor sie deren Arbeitsbereich zeigt. Wenn du die Website-Daten im Browser löschst oder die App entfernst, sind die Daten ebenfalls gelöscht.

## Benachrichtigungen auf deinem Gerät

[[Diesen Abschnitt nur behalten, wenn Benachrichtigungen in der Akquise-App aktiv sind; sonst den ganzen Abschnitt löschen. Danach diese Zeile löschen.]]

Schaltest du in der App Benachrichtigungen ein, speichert LeonAid für dein Gerät eine Adresse des Benachrichtigungsdienstes deines Browsers oder Betriebssystems (Google, Apple, Mozilla oder Microsoft) und zwei Schlüssel. Über diesen Dienst senden wir verschlüsselte Hinweise, zum Beispiel „3 Wiedervorlagen sind fällig“. Die Hinweise enthalten keine Namen, Adressen oder Beträge. Der Dienst erfährt, dass und wann dein Gerät einen Hinweis von LeonAid erhält, aber nicht dessen Inhalt. Rechtsgrundlage ist deine Einwilligung (Art. 6 Abs. 1 Buchst. a DSGVO). Du kannst sie jederzeit in der App unter „Benachrichtigungen“ widerrufen; LeonAid löscht die Adresse dann sofort. Sie wird auch gelöscht, wenn du dich auf dem Gerät abmeldest oder der Dienst sie als ungültig meldet.`;

/**
 * Proposals for the wording blocks of the part "Spenden"
 * (specs/mails-documents-donations-push/PLAN.md, Appendix A.3).
 * LEGAL REVIEW PENDING, as the header says: the liability note follows the
 * official sample for money donations and must be compared with the current
 * sample of the Federal Ministry of Finance before a real club uses it.
 */
export const DONATION_PLEDGE_TEXT_TEMPLATE =
  "Ihre Spende ist freiwillig. Sie erhalten dafür keine Gegenleistung. Dieses Schreiben ist keine Rechnung. Nach Eingang Ihrer Zahlung senden wir Ihnen eine Zuwendungsbestätigung für Ihre Steuererklärung.";

export const DONATION_RECEIPT_LIABILITY_TEMPLATE =
  "Hinweis: Wer vorsätzlich oder grob fahrlässig eine unrichtige Zuwendungsbestätigung erstellt oder veranlasst, dass Zuwendungen nicht zu den in der Zuwendungsbestätigung angegebenen steuerbegünstigten Zwecken verwendet werden, haftet für die entgangene Steuer (§ 10b Abs. 4 EStG, § 9 Abs. 3 KStG, § 9 Nr. 5 GewStG). Diese Bestätigung wird nicht als Nachweis für die steuerliche Berücksichtigung der Zuwendung anerkannt, wenn das Datum des Freistellungsbescheides länger als 5 Jahre bzw. das Datum der Feststellung der Einhaltung der satzungsmäßigen Voraussetzungen nach § 60a Abs. 1 AO länger als 3 Jahre seit Ausstellung des Bescheides zurückliegt (§ 63 Abs. 5 AO).";

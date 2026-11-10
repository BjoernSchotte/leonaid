---
title: Zuwendungsbestätigung ausstellen
description: Für eine bezahlte Spende die Zuwendungsbestätigung ausstellen, unterschreiben oder senden und sie bei einem Fehler für ungültig erklären.
docId: DOC-P060
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 026a2d563f8c79f01ba6f77016dbcf7334a4d602
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Charity-Admin der betroffenen Aktion oder globaler
`finance_manager`. Senden kann nur der Charity-Admin der Aktion.
`finance_reader` sieht Zuwendungsbestätigungen, kann aber nichts ändern.

Die Zuwendungsbestätigung ist der Beleg, mit dem ein Spender seine Spende in
der Steuererklärung geltend macht. LeonAid stellt sie nach dem amtlichen
Muster für Geldzuwendungen aus. Sie bestätigt, was eingegangen ist, nicht was
zugesagt war.

Die Texte und Regeln sind rechtlich noch nicht geprüft. Lass sie vor dem
ersten echten Einsatz von eurer Steuerberatung lesen.

## Voraussetzungen

- Die Spende ist **Bezahlt** (siehe
  [Spende erfassen](/de/user/how-to/record-donation/)).
- Der Bescheid der empfangenden Körperschaft ist nicht zu alt. Ein
  Freistellungsbescheid und die Anlage zum Körperschaftsteuerbescheid tragen
  Zuwendungsbestätigungen fünf Jahre ab ihrem Datum, ein Feststellungsbescheid
  nach § 60a AO drei Jahre. Danach zeigt die Spende einen Hinweis mit dem
  Datum, und ein System-Admin trägt unter **Rechtliches** im Teil **Spenden**
  den neuen Bescheid ein.

## Zuwendungsbestätigung ausstellen

1. Öffne im Backoffice **Spenden** und wähle die bezahlte Spende.
2. Wähle **Zuwendungsbestätigung ausstellen**.
3. Prüfe im Dialog den Betrag und den Tag des Zahlungseingangs. Beides steht
   danach auf der Bestätigung und lässt sich nicht mehr ändern.
4. Bestätige mit **Zuwendungsbestätigung ausstellen**. Weil dabei ein Beleg
   entsteht, bestätigst du deine Anmeldung gegebenenfalls erneut.

Die Zuwendungsbestätigung erhält eine eigene Nummer, zum Beispiel
**ZB26-0004**, und das Datum des Tages. Das PDF wird kurz danach erzeugt. Es
nennt die empfangende Körperschaft, den Spender, den Betrag in Ziffern und in
Buchstaben, den Tag der Zuwendung, den Bescheid, die begünstigten Zwecke und
den Haftungshinweis. Die Liste zeigt die Spende danach in der Ansicht
**Bestätigt**.

Zu einer Spende gibt es immer nur eine gültige Zuwendungsbestätigung.

## Unterschreiben oder senden

Wie die Bestätigung unterschrieben wird, legt der Teil **Spenden** unter
**Rechtliches** fest.

- **eigenhändig:** Das PDF hat eine Unterschriftszeile. Drucke es aus, lass
  es unterschreiben und gib das Original weiter. LeonAid sendet diese
  Bestätigung nicht per E-Mail, weil sie nur mit Unterschrift gilt.
- **maschinell:** Das PDF nennt die unterzeichnende Person und den Satz, dass
  es maschinell erstellt und das Verfahren dem Finanzamt angezeigt ist. Es
  gilt ohne Unterschrift. Wähle **Zuwendungsbestätigung senden**, sobald das
  PDF bereitsteht. Die E-Mail geht an die E-Mail-Adresse des Spenders. Ein
  fehlgeschlagener Versand lässt sich im selben Bereich erneut starten.

Die Bestätigung behält die Art der Unterschrift, die beim Ausstellen galt.

## Für ungültig erklären

Eine ausgestellte Zuwendungsbestätigung wird nie geändert. Ist sie falsch,
erklärst du sie für ungültig und stellst eine neue aus.

1. Wähle bei der Bestätigung **Für ungültig erklären**.
2. Trage den **Grund** ein, mindestens acht Zeichen.
3. Wähle, was mit dem Original beim Spender geschehen ist: **Das Original
   liegt uns wieder vor** oder **Das Finanzamt des Spenders ist informiert**.
   Ohne eine der beiden Angaben geht es nicht: Sonst könnte der Spender zwei
   Bestätigungen für eine Spende einreichen.
4. Bestätige mit **Für ungültig erklären**.

Eine ungültige Zuwendungsbestätigung wird nicht mehr versendet: Ein Versand,
der noch wartet oder fehlgeschlagen ist, endet mit dem Ungültig-Erklären und
lässt sich nicht neu starten. Geht gerade eine E-Mail hinaus, wartet LeonAid
kurz, bis sie verbucht ist; sie steht dann als gesendet bei der Bestätigung.

Die Bestätigung und ihr PDF bleiben gespeichert und stehen unter **Ungültige
Zuwendungsbestätigungen**. Das lässt sich nicht rückgängig machen. Danach
kannst du eine neue Zuwendungsbestätigung ausstellen; sie bekommt die nächste
Nummer.

## Zahlung und Zuwendungsbestätigung

Solange eine gültige Zuwendungsbestätigung besteht, lässt sich die Zahlung der
Spende nicht zurücknehmen. Erkläre zuerst die Bestätigung für ungültig.

## Aufbewahrung

Die empfangende Körperschaft bewahrt ein Doppel jeder Zuwendungsbestätigung
auf. LeonAid speichert jede Bestätigung mit ihrem PDF, auch die ungültigen.
Eine Datenschutz-Löschung lässt sie wie ausgestellte Rechnungen unverändert.

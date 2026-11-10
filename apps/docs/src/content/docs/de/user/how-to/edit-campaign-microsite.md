---
title: Aktions-Microsite bearbeiten
description: Texte und Bilder der öffentlichen Microsite einer Aktion im CMS-Editor ändern und veröffentlichen.
docId: DOC-P042
audience: [user]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: b18d63d1299216eefe09dee710699a4337cceeec
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

Du brauchst die Rolle Charity-Admin für die Aktion. Der Microsite-Editor
gehört zur optionalen Kampagnenseite. Seine Oberfläche ist englisch
beschriftet; diese Anleitung nennt die Beschriftungen unverändert. Läuft die
Installation ohne Kampagnenseite (`LEONAID_CMS_ENABLED=false`), zeigt LeonAid
weder **Microsite bearbeiten** noch den Navigationseintrag „Kampagnenseiten“.

1. Öffne in LeonAid die Aktion und wähle **Microsite bearbeiten**. Der Editor
   öffnet den aktuellen Entwurf der Seite.
2. Ändere die Textfelder. Der Editor speichert einige Sekunden nach der
   letzten Eingabe automatisch einen Entwurf und zeigt dann **Saved**.
   **Save** speichert den Entwurf sofort. Besucher sehen keinen Entwurf.
3. Um ein Bild hinzuzufügen oder zu ändern, wähle im Bildfeld **Select image**
   oder **Replace**. Der Dialog zeigt nur die Bilder dieser Aktion. Lade mit
   **Upload files** eine PNG-, JPEG- oder WebP-Datei hoch; sie ist danach
   automatisch ausgewählt. Bestätige mit **Select** oder **Replace**.
   **Remove** leert das Feld.
4. Zum Veröffentlichen wähle **Publish now** (erste Veröffentlichung) oder
   **Publish changes** und bestätige dieselbe Schaltfläche im Dialog. Die
   Seite ist sofort sichtbar; **Live View** öffnet sie auf der öffentlichen
   Adresse des Clubs, auch wenn der Editor auf dem Verwaltungshost läuft.
   Solange die Aktion im Veröffentlichungszeitraum aktiv ist, steht sie
   zusätzlich auf der öffentlichen Startseite unter **Aktuelle Aktionen**.
5. **Discard changes** im Bereich **Publish** verwirft den Entwurf und kehrt
   zur veröffentlichten Fassung zurück.
6. Mit **Zurück zu LeonAid** kehrst du in die LeonAid-Verwaltung zurück.

Du kannst weitertippen, während der Editor speichert oder veröffentlicht;
deine Eingabe bleibt erhalten und wird mit dem nächsten automatischen
Speichern gesichert. Verlässt du die Seite mit ungespeicherter Eingabe, fragt
der Browser vorher nach.

Adresse der Seite, zugehörige Aktion und Veröffentlichungszeitraum verwaltet
LeonAid. Änderungen am Slug, am Veröffentlichungsdatum, an einer Planung oder
an Bylines werden abgelehnt; der Editor zeigt dann eine Fehlermeldung.
Veröffentlichen schlägt auch fehl, solange die Aktion in LeonAid außerhalb
ihres Veröffentlichungszeitraums liegt.

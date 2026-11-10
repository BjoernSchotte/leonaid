---
title: Meine Tour fahren
description: Die Lieferstopps in der App abarbeiten, Lieferungen abhaken, Stopps umsortieren und offline weiterarbeiten.
docId: DOC-P052
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 278f0c5658d87a7aaa1829609e883c816d35340b
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Rolle:** Ausfahrer. Der Tab **Tour** in der App (Menüeintrag **Meine Tour**) erscheint nur,
wenn das Feature-Flag `delivery.tours` an ist. Ohne Flag nutze
**Auslieferung** (siehe
[Auslieferung abhaken](/de/user/how-to/work-delivery-board/)).

## Tour abarbeiten

1. Öffne **Tour**. Du siehst nur deine eigenen Stopps des Liefertags, mit
   Adresse, Kontakt und Menge, ohne Beträge.
2. Der feste Block **Nächster Stopp** unten zeigt den nächsten offenen Stopp.
   Er hat **Zugestellt** und **Nicht da**.
3. Die Karte zeigt deine Stopps. Ein zusätzlicher Link öffnet den Ort in
   OpenStreetMap.
4. Ein **Hinweis für den Fahrer** vom Kunden steht im Block „Nächster Stopp“
   und in der Stoppzeile.

Zugestellte Stopps bleiben an ihrem Platz, grau dargestellt. Klappe einen auf,
um ihn wieder zu sehen.

## Umsortieren

Ziehe einen Stopp am Griff. LeonAid speichert beim Ablegen und zeigt
**Rückgängig**. Um zur Reihenfolge der Planung zurückzukehren, wähle **Zurück
zur Planung** im ⋮-Menü.

## Offline

Offline (Feature-Flag `pwa.offline_queue` ebenfalls an): Die App hält deine
Tour zwischengespeichert und zeigt **Offline – Stand HH:MM**. Offline speichert
LeonAid Zustellungen und deine Reihenfolge auf dem Gerät und sendet sie, sobald
du online bist; hat die Planung inzwischen geändert, steht der Eintrag unter
„Du“ als „Vom Planer geändert“ oder „Fenster geschlossen“.

Die zwischengespeicherte Tour wird entfernt, wenn das Fenster geschlossen
wird, 12 Stunden nach Fensterende, beim Abmelden und wenn das Flag
ausgeschaltet wird. Kartenkacheln werden nicht für offline gespeichert. Die
Liste funktioniert ohne Karte.

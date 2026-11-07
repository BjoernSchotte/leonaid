---
title: Rollen und Zugriffsbereiche
description: Referenz der implementierten globalen und aktionsbezogenen LeonAid-Rollen.
docId: DOC-P016
audience: [user]
diataxis: reference
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

| Rolle             | Bereich                    | Darf im aktuellen Stand                                                                 |
| ----------------- | -------------------------- | --------------------------------------------------------------------------------------- |
| `system_admin`    | global                     | Benutzer, globale Rollen, Integrationen, Datenschutz- und Betriebsfunktionen verwalten  |
| `finance_reader`  | global oder Aktion         | Rechnungen, PDFs, Versand, Zahlungen und offene Posten lesen                            |
| `finance_manager` | global                     | Zahlungen buchen und zurückbuchen, Rechnungen kontrolliert stornieren                   |
| `charity_admin`   | eine Aktion                | Aktion, Mitglieder, Bestellungen, Rechnungen und Finanzaktionen dieser Aktion verwalten |
| `acquirer`        | eine Aktion                | zugeordnete Sponsoren, Aktivitäten und Bestellungen bearbeiten                          |
| `driver` (UI: **Ausfahrer**) | Aktion mit Lieferfähigkeit | in der App **Auslieferung** nur die eigenen zugewiesenen Lieferungen mit Adresse und Kontakt, ohne Beträge, sehen und abhaken, solange das Fenster offen ist |

Eine Person kann mehrere Rollen besitzen. Aktionsrollen gelten nur für die
angegebene Charity-Aktion. Ein Charity-Admin erhält dadurch keine Rechte auf
andere Aktionen und keine globale Rolle. Ein Akquisiteur sieht keine
Rechnungen. Die Oberfläche blendet unzulässige Aktionen aus; der Server prüft
dieselben Grenzen bei jedem Request.

Globale Rollen vergibt nur ein System-Admin. Ein Charity-Admin darf
Aktionsrollen nur in selbst verwalteten Aktionen ändern. Änderungen wirken ab
dem nächsten Request und benötigen für kritische Verwaltungsaktionen eine
frisch bestätigte Anmeldung.

## Startbereich nach der Anmeldung

Nach der Anmeldung öffnet LeonAid den Bereich, der zu deinen Rollen passt.
Mit eigenem Verwaltungshost (`app.<domain>`) gilt das auch, wenn du nur die
Adresse eingibst:

| Rollen                                   | Startbereich                     |
| ---------------------------------------- | -------------------------------- |
| eine Akquise-Rolle (auch neben anderen)  | Akquise-App                      |
| `system_admin`                           | Verwaltung, Seite **System**     |
| `charity_admin`                          | Verwaltung, Übersicht            |
| Finanzrollen                             | Verwaltung, **Rechnungen**       |
| nur Ausfahrer oder keine Verwaltungsrolle | Akquise-App                     |

Hast du Rollen für beide Bereiche, wechselst du mit **Akquise-App** in der
Leiste der Verwaltung oder mit **Zur Verwaltung** unter **Mehr** in der App.
In der Befehlspalette der Verwaltung wählst du **Verwaltung als Startbereich
verwenden**, in der App unter **Mehr** **Akquise-App als Startbereich
verwenden**. LeonAid merkt sich die Wahl, solange du eine Rolle für diesen
Bereich hast. Nach einer Wahl bieten dir beide Stellen auch
**Standard-Startbereich verwenden** an: Die Wahl entfällt, und die Tabelle
oben gilt wieder. Öffnest du einen Link auf eine bestimmte Seite, landest du nach der
Anmeldung genau dort.


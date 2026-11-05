---
title: Rollen und Zugriffsbereiche
description: Referenz der implementierten globalen und aktionsbezogenen LeonAid-Rollen.
docId: DOC-P016
audience: [user]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 625bbfb87f7406f8811245356849f830b4321ab7
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

| Rolle             | Bereich                    | Darf im aktuellen Stand                                                                 |
| ----------------- | -------------------------- | --------------------------------------------------------------------------------------- |
| `system_admin`    | global                     | Benutzer, globale Rollen, Integrationen, Datenschutz- und Betriebsfunktionen verwalten  |
| `finance_reader`  | global oder Aktion         | Rechnungen, PDFs, Versand, Zahlungen und offene Posten lesen                            |
| `finance_manager` | global                     | Vollzahlungen buchen und Rechnungen kontrolliert stornieren                             |
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

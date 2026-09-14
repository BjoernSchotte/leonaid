---
title: Rollen und Zugriffsbereiche
description: Referenz der implementierten globalen und aktionsbezogenen LeonAid-Rollen.
docId: DOC-P016
audience: [user]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

| Rolle             | Bereich                    | Darf im aktuellen Stand                                                                 |
| ----------------- | -------------------------- | --------------------------------------------------------------------------------------- |
| `system_admin`    | global                     | Benutzer, globale Rollen, Integrationen, Datenschutz- und Betriebsfunktionen verwalten  |
| `finance_reader`  | global oder Aktion         | Rechnungen, PDFs, Versand, Zahlungen und offene Posten lesen                            |
| `finance_manager` | global                     | Vollzahlungen buchen und Rechnungen kontrolliert stornieren                             |
| `charity_admin`   | eine Aktion                | Aktion, Mitglieder, Bestellungen, Rechnungen und Finanzaktionen dieser Aktion verwalten |
| `acquirer`        | eine Aktion                | zugeordnete Sponsoren, Aktivitäten und Bestellungen bearbeiten                          |
| `driver`          | Aktion mit Lieferfähigkeit | Rolle ist modelliert; der produktive Fahrer-/Tourenworkflow ist zurückgestellt          |

Eine Person kann mehrere Rollen besitzen. Aktionsrollen gelten nur für die
angegebene Charity-Aktion. Ein Charity-Admin erhält dadurch keine Rechte auf
andere Aktionen und keine globale Rolle. Ein Akquisiteur sieht keine
Rechnungen. Die Oberfläche blendet unzulässige Aktionen aus; der Server prüft
dieselben Grenzen bei jedem Request.

Globale Rollen vergibt nur ein System-Admin. Ein Charity-Admin darf
Aktionsrollen nur in selbst verwalteten Aktionen ändern. Änderungen wirken ab
dem nächsten Request und benötigen für kritische Verwaltungsaktionen eine
frisch bestätigte Anmeldung.

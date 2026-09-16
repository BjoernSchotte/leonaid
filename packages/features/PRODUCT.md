# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users and purpose

LeonAid unterstützt die Verwaltung und Durchführung von gemeinnützigen Aktionen. Die gemeinsamen Funktionen dieses Pakets werden in der Verwaltungs-Weboberfläche und der mobilen PWA verwendet.

## Capabilities and constraints

Maßgeblich ist [die Modularisierungs-Spec](../../specs/modular-platform/PLAN.md). Tasks, Wissen, Materialien und Inbox nutzen gemeinsame Fach-APIs und aktuelle Berechtigungen. Verweise erweitern keine Zugriffsrechte. Twenty bleibt die Quelle der Kontaktstammdaten. Öffentliche Inbox-Eingänge versenden keine E-Mail.

## Implementation direction

Aus der bestehenden Implementierung übernommen: deutsche Bedienoberfläche, gemeinsame React-Komponenten und Gestaltungstokens, Tastaturbedienbarkeit sowie mobile Ansichten. Die neue Inbox erweitert diese Oberfläche. Es wird keine neue visuelle Identität eingeführt.

Dieser Kontext wurde aus der beauftragten Spec und dem vorhandenen Code abgeleitet; der Nutzer hat die autonome Umsetzung beauftragt. Zusätzliche Zielgruppen- oder Positionierungsannahmen sind nicht festgelegt.

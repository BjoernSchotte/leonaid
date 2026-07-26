# Web

React-Backoffice für Charity-Administration und Finanzen.

Der POC-040-Zwischenstand liefert bereits eine responsive, serverseitig
berechtigte Persona-Shell über den gemeinsamen Compose-Frontend-Host. Die
endgültige React-/shadcn-Komponentenarchitektur und der vollständige
Komponentenkatalog folgen gebündelt in POC-100.

Seit POC-041 enthält `/admin/members` zusätzlich den realen
Einladungsablauf. Die auswählbaren Aktionen und Rollen kommen ausschließlich
vom berechtigten Core-Endpunkt; ein Charity-Admin sieht dabei nur die eigenen
verwalteten Aktionen. Erfolg, Validierungsfehler, leere Auswahl und Ladezustand
sind bedienbar. Die Oberfläche bleibt eine bewusst kleine Zwischenstufe bis
zur gemeinsamen React-/shadcn-Umsetzung in POC-100.

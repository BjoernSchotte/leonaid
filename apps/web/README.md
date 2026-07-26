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

POC-042 schützt die Shell mit einer serverseitigen, absolut 90 Tage gültigen
Sitzung. Die Oberfläche bietet einen echten Logout. Sensible Admin-Aufrufe
fordern bei abgelaufener Frische gezielt zur erneuten Anmeldung auf und führen
anschließend zum beabsichtigten internen Ziel zurück; normale Arbeit bleibt
innerhalb der gültigen Sitzung ohne erneuten Login möglich.

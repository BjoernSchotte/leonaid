# PWA

Mobile-first React-PWA für Akquisiteure und aktionsbezogene Rollen.

Der POC-040-Zwischenstand beweist bereits mobile Persona-Navigation und
Aktionssicht gegen echte Core-Sitzungen. Installierbarkeit, Offline-Hinweis
und die fachliche Sponsoroberfläche werden erst mit POC-062 abgenommen.

POC-043 stellt dafür bereits den abgesicherten Datenzugang bereit: Die PWA
spricht ausschließlich mit der LeonAid-Core-API und kennt weder Twenty-Login
noch Twenty-Key. Listen, Suche, Counts, Export, Aktivitäten und Dokumente
verwenden dort denselben aus Sitzung, Membership und Assignment abgeleiteten
Scope.

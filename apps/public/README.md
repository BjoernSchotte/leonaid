# Public Web

Öffentliche Astro-Aktionsseiten und Standardformulare.

POC-041 stellt unter `/invite` bereits eine responsive Aktivierungsseite für
Magic Link und sechsstelligen Code bereit. Ein Link führt aus Schutz vor
Mail-Scannern nicht automatisch eine schreibende Aktion aus: Das Token wird
aus der sichtbaren URL entfernt und erst nach ausdrücklicher Bestätigung an
die Core-API gesendet. Der erfolgreiche Abschluss aktiviert Konto und
Aktionsrolle; eine dauerhafte 90-Tage-Sitzung folgt in POC-042.

Die öffentliche Aktionsdarstellung, Alias-/Archivlogik und Bestellformulare
werden als Astro-Anwendung in POC-070 bis POC-072 umgesetzt.

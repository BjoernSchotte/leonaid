# Public Web

Öffentliche Astro-Aktionsseiten und Standardformulare.

POC-041 stellt unter `/invite` eine responsive Aktivierungsseite für
Magic Link und sechsstelligen Code bereit. Ein Link führt aus Schutz vor
Mail-Scannern nicht automatisch eine schreibende Aktion aus: Das Token wird
aus der sichtbaren URL entfernt und erst nach ausdrücklicher Bestätigung an
die Core-API gesendet. Der erfolgreiche Abschluss aktiviert Konto und
Aktionsrolle und startet unmittelbar eine sichere 90-Tage-Sitzung.

POC-042 ergänzt unter `/login` den passwortlosen Mitglieder-Login per Magic
Link oder sechsstelligen Code. Die Antwort verrät nicht, ob eine E-Mail
registriert ist. `/fresh-login` bestätigt sensible Aktionen erneut, entfernt
Magic-Link-Tokens vor der Bestätigung aus der sichtbaren URL und führt danach
nur zu einem geprüften internen Rücksprungziel.

Die öffentliche Aktionsdarstellung, Alias-/Archivlogik und Bestellformulare
werden als Astro-Anwendung in POC-070 bis POC-072 umgesetzt.

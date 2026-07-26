# Public Web

Serverseitig gerenderte öffentliche Astro-Aktionsseiten sowie die
passwortlosen Einstiege für Mitglieder.

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

POC-071 liefert die öffentliche Aktionsdarstellung für Alias- und
Archiv-Adressen. Astro fragt ausschließlich den FastAPI-Core über den
generierten Client ab. Die fachliche Entscheidung über Veröffentlichung,
Archiv und öffentliche Angebote bleibt vollständig im Core. Aktionsseiten
enthalten kein Client-JavaScript; Schriften und Bildmotive werden lokal
ausgeliefert.

Das öffentliche Bestellformular folgt in POC-072. Seine Astro Action darf
Transportdaten validieren, Spam-Signale erfassen und an den Core
weiterleiten. Preise, Verfügbarkeit, Bestellfenster und alle weiteren
Fachregeln werden dort erneut entschieden.

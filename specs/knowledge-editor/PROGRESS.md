# Umsetzung des Wissenseditors

## Slice 1: gespeicherte Formatierungen und allgemeine Toolbar

Ausgangsstand `42539e2`. Der vorhandene Tiptap-Editor bietet Unterstreichen,
Durchstreichen, Schriftfamilie/-größe, sichere Linkbearbeitung, Absatzstile,
Listen, Ein-/Ausrücken und Ausrichtung. TextStyle/TextAlign sind exakt auf
3.31.3 gepinnt. Der Backend-Vertrag erlaubt nur definierte Schriftwerte und
Absatzattribute; alte Dokumente bleiben gültig. Die Schreibfläche erhält
mindestens 65 Prozent der Viewporthöhe beziehungsweise 32 rem.

53 Dokumenttests, Ruff, Mypy, Features-TypeScript und No-Test-Doubles bestanden.
`sh tools/testing/modular_browser.sh .` bestand vollständig mit Exit 0: sieben
Produktionsbrowserfälle, einschließlich Schrift-/Unterstreichungs-/Ausrichtungs-
Roundtrip über Web/PWA und erhaltenem Konfliktentwurf. Lauf 34358; Log
`/tmp/leonaid-knowledge-toolbar-browser.log`. Desktop-/Mobile-Screenshots wurden
angesehen und am PR angehängt. Der isolierte Runner hat seinen Stack entfernt.

Zum Abschluss dieses Slices noch offen: Auswahlmenü, kompakter Dokumentkopf und gemeinsame Einfügeaktionen.
Die erste mobile Aufnahme zeigt, dass vor der Schreibfläche noch zu viele
Verwaltungselemente stehen; der zweite Slice verschiebt diese in den Dokumentkopf
und prüft die Auswahlposition gegenüber der festen PWA-Navigation.


## Slice 2: Auswahlmenü und Dokumentkopf

Die Auswahlleiste besteht aus genau einer Zeile mit sechs Icons. Weitere Formate
öffnen ein eigenes Bedienfeld; die Hauptzeile bricht dabei nicht um. Allgemeine
Toolbar und Auswahlmenü verwenden dieselben Formatierungsaktionen. Der Kopf
bündelt Titel, Speicherstatus und Speicheraktionen; Freigaben und Einfügen von
Aufgaben/Materialien sind einklappbar.

Die Browserprüfung erfasst Auswahl, Schriftwechsel im Untermenü, Linkeingabe,
Escape, gespeicherte Formatierung und Konfliktentwurf in Web/PWA. Escape setzt den
Cursor ans Auswahlende. Der native Tastaturzugriff berücksichtigt Tiptaps
Event-Weitergabe. Bei Alles markieren verankert sich das Menü innerhalb der
Textblöcke statt an der hohen Dokumentfläche. Die Abnahme misst eine einzige
Icon-Zeile, Viewportgrenzen und weniger als 24 px Abstand zum ausgewählten Absatz.

Der vollständige Modul-Browserlauf vom 14.09.2026 besteht mit sieben Fällen;
Log `/tmp/leonaid-knowledge-selection-browser-4.log`, isoliertes Projekt
`leonaid-shared-2bed92392f53f536`. Desktop und Mobile wurden visuell geprüft.
TypeScript, Diffprüfung und Impeccable-Detektor bestehen. Der Secret-Scan umfasst
die vorbereiteten Quelldateien. Die CI für Slice 1 ist ebenfalls vollständig grün.

Zum Abschluss dieses Slices noch offen: Copy/Paste-Normalisierung und erweiterte Gesamtabnahme einschließlich
Touch-Zielen, Listen/History, gemischter Auswahl, Referenzen und Leserechten.


## Slice 3: einzeilige Haupt-Toolbar und Gesamtabnahme

Auch die Haupt-Toolbar bleibt einzeilig. In schmalen Ansichten wandern Schrift-,
Absatz-, Listen- und Ausrichtungssteuerung in das Drei-Punkte-Menü; dessen
Bedienfeld liegt über dem Inhalt und verlängert die Toolbar nicht. Sichtbare
Toolbar-Buttons werden bei der Pfeiltastennavigation berücksichtigt. Ein- und
Ausrückverfügbarkeit wird aus der aktuellen Editor-Auswahl beobachtet.

Ein kleiner DOMParser-Schritt normalisiert fremde Schriftwerte und Linkattribute
vor Tiptaps HTML-Paste. Toolbar und Normalisierung verwenden dieselben erlaubten
Schriftwerte. Der Backend-Vertrag akzeptiert zusätzlich Tiptaps leere
Schriftwerte als nicht gesetzt; andere Werte bleiben auf der Whitelist. Die
Browser-Seeds verwenden synthetische example.org-Adressen, da EmailStr
example.invalid zurückweist.

Drei zusätzliche echte Browserfälle sind in den bestehenden Modul-Runner
aufgenommen: Zwischenablage/partielle Auswahl/Listen/History für Desktop und Touch-
PWA sowie Aufgaben-/Materialeinfügen, Nur-Lesen und Zugriffsentzug. Tastatureingaben
laufen über native Eingaben; die Mausauswahl trifft das gerenderte Wort statt den
Leerraum einer Listenzeile. Die Auswahl wird vor dem Formatieren explizit geprüft.

Die vollständige Modul-Abnahme vom 14.09.2026 besteht mit **zehn Browserfällen**
und Exit 0. Log: `/tmp/leonaid-editor-complete-proof.log`; isoliertes Projekt
`leonaid-shared-9c6edbeda9d87ce8`. Haupt- und Auswahltoolbar bleiben jeweils in
einer Zeile; die Touch-PWA erfüllt 44-px-Bedienziele ohne horizontalen Überlauf.
Desktop-/PWA-Aufnahmen zu Formatierung, Listen, Referenzen und Leserechten wurden
visuell geprüft und werden als Screenshot-Kommentar am Draft-PR veröffentlicht.

57 Dokumenttests, Ruff, Mypy, Features-TypeScript, Formatierung, No-Test-Doubles,
Diffprüfung und Secret-Scan der vorbereiteten Quell-/Testdateien bestehen. Die
vollständige CI für Slice 2 (`d4d9d12`) ist grün; die neue Commit-CI startet mit dem
Push. Die Aufgabenverwaltung wurde in diesem Editor-Slice nicht umgebaut.

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

Noch offen: Auswahlmenü, kompakter Dokumentkopf und gemeinsame Einfügeaktionen.
Die erste mobile Aufnahme zeigt, dass vor der Schreibfläche noch zu viele
Verwaltungselemente stehen; der zweite Slice verschiebt diese in den Dokumentkopf
und prüft die Auswahlposition gegenüber der festen PWA-Navigation.

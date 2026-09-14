# Wissenseditor mit Dokumentfläche und Auswahlformatierung

Beauftragt: große dokumentartige Schreibfläche, allgemeine Toolbar und ein
Formatierungsmenü an ausgewähltem Text, analog zum beschriebenen Confluence-Ablauf.
Bestehendes Tiptap, Web/PWA, Fach-APIs und Konfliktschutz bleiben Grundlage.
Yjs/Hocuspocus und zusätzliche Dienste sind nicht Bestandteil dieses Ausbaus.

## Slices

- [x] Durchgängiger Formatierungsvertrag und allgemeine Toolbar: Fett, Kursiv,
      Unterstreichen, Durchstreichen, sichere Links, Absatz/Überschrift, Schriftart,
      Schriftgröße, ungeordnete/nummerierte Listen, Ein-/Ausrücken, Ausrichtung,
      Undo/Redo; große Schreibfläche. Backend validiert neue Attribute eng;
      bestehende Dokumente und Task-/Materialreferenzen bleiben lesbar.
- [x] Gemeinsames Auswahlmenü mit Tiptap BubbleMenu; erhaltene Auswahl bei
      Klick, Dropdowns und Linkeingabe; einzeilige Icon-Leiste und explizites Menü für weitere Formate.
      Seitenkopf mit Titel/Speicherstatus/Freigaben, Einfügen für Tasks/Materialien.
- [ ] Gesamtabnahme: Desktop und mobile PWA, Auswahl per Maus/Tastatur,
      Speichern/Wiederöffnen, gemischte Formate, Copy/Paste, Undo/Redo,
      Rechte/Read-only, Konfliktentwurf, kein Überlauf; bestehende Modulregression.

Jeder abgeschlossene Slice wird auf Draft-PR #7 gepusht. Tatsächliche Browser-
Screenshots werden visuell geprüft und als PR-Kommentar angehängt. Keine
Abnahme allein aufgrund von Build oder Unit-Tests.

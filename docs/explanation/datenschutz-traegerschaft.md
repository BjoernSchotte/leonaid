# Datenschutz: Trägerschaft & Haftung — Gesprächsgrundlage

*Bezug: [`../architektur.md`](../architektur.md) §9 · Stand: 2026-05-29*

> ⚠️ **KEINE RECHTSBERATUNG.** Quellenbasierte Orientierung für ein Gespräch mit der Clubleitung;
> die finale Bewertung gehört zu den Club-Anwälten und ggf. einem Datenschutzbeauftragten (DSB).
> Erstellt aus einer verifizierten Web-Recherche (Aufsichtsbehörden-Orientierungshilfen + aktuelle
> EuGH-/BGH-Rechtsprechung; 25 Aussagen adversariell geprüft, 22 bestätigt, 3 verworfen).
>
> **Begleitdokumente:** [Beschlussvorlage](datenschutz-beschlussvorlage.md) ·
> [Fragenliste an die Anwälte](datenschutz-anwaltsfragen.md)

## Kernbotschaft (für den ehrenamtlichen Techniker)

Die Beweislage zeigt in eine **günstige Richtung**: Verantwortlicher ist der *Verein*, nicht die
handelnde Einzelperson — die pauschale Formel „der Vorstand haftet" wurde von den Prüfern sogar
**widerlegt**. **Aber** die *Detail*-Haftungsfragen (§§ 31a/31b BGB, § 42 BDSG, EuGH-Linie zur
Hilfspersonenhaftung) ließen sich **nicht mit Primärquellen absichern** → die müssen die Anwälte
final klären (siehe [Fragenliste](datenschutz-anwaltsfragen.md)).

## 1. Wer ist „Verantwortlicher" (Art. 4 Nr. 7 DSGVO)? *(belegt)*

- Verantwortlicher ist **der Verein selbst** als „andere Stelle", die über **Zwecke und Mittel**
  entscheidet — **unabhängig** von der Registereintragung. Auch der **nicht rechtsfähige Lions
  Club** kann Verantwortlicher sein (LDI NRW: „unerheblich, ob der Verein ins Vereinsregister
  eingetragen ist").
- **Wer den Hetzner-Vertrag zeichnet/zahlt, begründet die Verantwortlicheneigenschaft NICHT** —
  sie richtet sich danach, wer über Zwecke (Akquise, Mitgliederverwaltung) und Mittel (das CRM)
  bestimmt. Bündeln beim e.V. ist v.a. *operativ* sinnvoll.
- In Betracht: Club, **Hilfswerk e.V.** oder **gemeinsame Verantwortlichkeit (Art. 26)** →
  anwaltlich/DSB festzulegen und zu dokumentieren.
- **Praxis-Punkt:** Verträge (Hetzner, E-Mail) besser über den **rechtsfähigen e.V.** schließen —
  u.a. wegen möglicher **Handelndenhaftung § 54 S. 2 BGB** beim nicht rechtsfähigen Club (das ist
  Vertrags-, nicht DSGVO-Haftung; anwaltlich bestätigen).

> **Tendenz:** Verantwortung möglichst klar **beim Hilfswerk e.V.** bündeln (rechtsfähig, führt
> die Kasse, zeichnet Verträge). Ob „e.V. allein" oder „Art. 26 gemeinsam", entscheiden die Juristen.

## 2. Pflichten des Verantwortlichen *(belegt)*

- **VVT (Art. 30), TOMs (Art. 32, inkl. Transportverschlüsselung), Betroffenenrechte (Art. 15–21),
  Datenpanne-Meldung (Art. 33/34, 72 h).**
- **Informationspflicht: Sponsoren = Art. 14** (nicht beim Betroffenen erhoben → aktive
  Information, spätestens bei Erstkontakt). Mitglieder = Art. 13.
- **AV-Vertrag (Art. 28)** beim Hosting (Hetzner-DPA: `hetzner.com/AV/DPA_de.pdf`) und i.d.R. beim
  E-Mail-Provider.
- **Rechtsgrundlage Art. 6 Abs. 1:** berechtigtes Interesse vs. Einwilligung für die
  B2B-Sponsorenansprache (vgl. architektur.md §9).
- **DSB-Pflicht:** erst ab **i.d.R. 20 Personen**, die *ständig automatisiert* verarbeiten
  (§ 38 Abs. 1 S. 1 BDSG; 2019 von 10→20 angehoben) → bei kleinem Club regelmäßig **nicht**.
  - **Auffang-Tatbestand § 38 Abs. 1 S. 2 BDSG:** DSB-Pflicht **unabhängig von der Personenzahl**,
    wenn eine **DSFA (Art. 35)** nötig ist *oder* Daten **„geschäftsmäßig zur Übermittlung /
    Markt-/Meinungsforschung"** verarbeitet werden → bei umfangreichen Akquiselisten **prüfen**.
  - *(Eine ältere LfDI-BW-Hilfe wurde fälschlich mit „2 Personen" wiedergegeben — maßgeblich: **20**.)*

## 3. Haftung des Vereins *(belegt, aktuelle Rechtsprechung)*

- **Schadensersatz Art. 82:** drei **kumulative** Voraussetzungen (Verstoß + tatsächlicher Schaden
  + Kausalität); bloßer Verstoß genügt **nicht** (**EuGH C-300/21**, 04.05.2023), aber **keine
  Erheblichkeitsschwelle**. **BGH VI ZR 10/24 (18.11.2024, Leitentscheidung):** schon der **bloße,
  kurzzeitige Kontrollverlust** kann ein ersatzfähiger immaterieller Schaden sein. Fortgeführt: BGH
  VI ZR 365/22 (11.02.2025), EuGH C-655/23 (04.09.2025). → Ein Datenleck der CRM-VM kann Ansprüche
  auslösen; Schuldner ist **primär der Verein**.
- **Bußgeld Art. 83:** kann **direkt gegen die juristische Person** (e.V.) verhängt werden, **ohne**
  Zuordnung zu einer natürlichen Person (**EuGH C-807/21 „Deutsche Wohnen", 05.12.2023**) — aber
  **Verschulden** nötig. Bußgeld-Adressierbarkeit des *nicht rechtsfähigen* Clubs: gesondert prüfen.

## 4. Persönliche Haftung — die Kernfrage *(teils belegt, Kern offen)*

**Belegt / günstige Richtung:**
- Verantwortlicher ist **der Verein**, nicht die handelnde Person. Drei pauschale
  „Vorstand haftet / ist Verantwortlicher"-Aussagen wurden in der Prüfung **0:3 widerlegt**.
- In den Quellen: BGH-Linie, dass **Arbeitnehmer grundsätzlich nicht „Verantwortliche"** i.S.v.
  Art. 4 Nr. 7 sind → spricht stark dagegen, dass ein unentgeltliches Nicht-Vorstands-Mitglied,
  das *für* den Verantwortlichen handelt, selbst Verantwortlicher/primärer Art.-82-Schuldner ist.

**Nicht primärquellenbelegt → zwingend anwaltlich klären:**
- Greifen **§ 31a BGB** (Vorstand) bzw. **§ 31b BGB** (unentgeltlich tätige *Mitglieder* → Haftung
  nur bei **Vorsatz/grober Fahrlässigkeit**)?
- **Strafbarkeit § 42 BDSG** (i.d.R. Vorsatz + Bereicherungs-/Schädigungsabsicht → bloße
  Technikarbeit normalerweise nicht erfasst — *unbestätigt*).
- **EuGH-Linie zur Hilfspersonen-/Mitarbeiterhaftung** und Entlastung des Verantwortlichen.

## 5. Wie der ehrenamtliche Techniker sein Risiko minimiert

*(organisatorisch sinnvoll; Tragfähigkeit von Freistellung/Versicherung anwaltlich bestätigen)*

1. **Dokumentierte Beauftragung per Vorstandsbeschluss** (benennt Verantwortlichen + begrenzte,
   weisungsgebundene Rolle) → [Beschlussvorlage](datenschutz-beschlussvorlage.md).
2. **Nur auf Weisung / im Rahmen handeln** — kein Alleingang, keine eigenen Zweckentscheidungen.
3. **Schriftliche Freistellungserklärung** des Vereins (Innenregress-Verzicht).
4. **Versicherung des Vereins** mit Datenschutz-/Vermögensschaden-Baustein (Vereins-Haftpflicht;
   ggf. D&O / „Ehrenamtsversicherung" der Länder).
5. **Kein Auftreten als „Betreiber" nach außen**; **e.V. ist Vertragspartner** bei Hetzner &
   E-Mail und hält Keys/Zugänge (passt zur Architektur: ein zentraler API-Key serverseitig).

## 6. Checkliste für die Clubleitung

a) **Verantwortlichen festlegen & dokumentieren** (Club / e.V. / Art. 26) — nach Entscheidungsmacht.
b) **Hetzner-AVV + E-Mail-AVV (Art. 28)** schließen — wer zeichnet? (→ e.V.)
c) **DSB-Prüfung:** 20-Personen-Schwelle *und* Auffang § 38 Abs. 1 S. 2 (DSFA / „geschäftsmäßig").
d) **Rechtsgrundlage Art. 6** + Informationspflichten (Art. 14 Sponsoren).
e) **VVT, TOMs, Datenpanne-Meldeprozess.**
f) **Versicherung + schriftliche Beauftragung/Freistellung** des Technik-Ehrenamtlichen.
g) **Satzungs-/Beschlusslage** dokumentieren.

## 7. Lions-spezifisch

- Offizielle Datenschutzseite `lions.de/datenschutz`; Hinweis auf ein „Datenschutz
  LIONS-Hilfswerk"-PDF (technisch nicht auslesbar); Club-Beispiele (z.B. LC München-Marienplatz).
  → bei **MD 111 / Lions Clubs International** nach aktuellen **Mustervorlagen** fragen.
- Guter Einstieg: **Stiftung Datenschutz – „Basiswissen Datenschutz im Verein"**
  (`stiftungdatenschutz.org/ehrenamt`).

## 8. Ehrliche Einordnung

| | |
|---|---|
| **Relativ klar** | Auch der nicht rechtsfähige Club ist DSGVO-fähig & kann Verantwortlicher sein · Verantwortlicher = der *Verein*, nicht persönlich der Vorstand · DSB-Schwelle 20 + Auffang § 38 Abs. 1 S. 2 · AVV-Pflicht beim Hosting · Art. 82 auch bei bloßem Kontrollverlust · Art. 83-Bußgeld direkt gegen die juristische Person (mit Verschulden). |
| **Strittig / offen → Anwälte + DSB** | Persönliche Haftung im Detail (§§ 31a/31b BGB, § 42 BDSG, Hilfspersonenhaftung) · ob Club/e.V./Art. 26 · ob DSFA/„geschäftsmäßig" → DSB-Pflicht · Bußgeld-Adressierbarkeit des Clubs · Tragfähigkeit von Freistellung/Versicherung · § 54 S. 2 BGB. |
| **Zeitsensitiv** | Vorstoß, DSB-Schwelle 20→50 anzuheben (Wachstumsinitiative 05.07.2024) — **noch nicht in Kraft** · Art.-82-Rechtsprechung entwickelt sich dynamisch (zuletzt 2025) → vor finaler Beratung Stand prüfen. |

## Quellen (Auswahl, verifiziert)

- Aufsichtsbehörden-Orientierungshilfen: LfDI Baden-Württemberg, LDI NRW, LfDI Rheinland-Pfalz,
  Hessen, Sachsen (Datenschutz im Verein).
- Gesetzestext: § 38 BDSG (`gesetze-im-internet.de/bdsg_2018/__38.html`); § 42 BDSG (dejure.org).
- Rechtsprechung: BGH PM 218/2024 zu **VI ZR 10/24**; **EuGH C-300/21** (04.05.2023);
  **EuGH C-807/21 „Deutsche Wohnen"** (05.12.2023) — über dejure.org / bundesgerichtshof.de.
- Hetzner DPA (`hetzner.com/AV/DPA_de.pdf`); Stiftung Datenschutz (`stiftungdatenschutz.org/ehrenamt`).

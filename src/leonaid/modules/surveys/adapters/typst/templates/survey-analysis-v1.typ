#let data = json("report.json")
#let blue = rgb("#00338d")
#let ink = rgb("#172033")
#let muted = rgb("#526174")
#let border = rgb("#d8dee9")
#let surface = rgb("#f0f4fa")

#set document(title: data.title, author: "LeonAid Surveys", keywords: ("Umfragen", data.snapshotId, data.renderVersion))
#set page(paper: "a4", margin: (x: 19mm, top: 17mm, bottom: 19mm), footer: context [
  #set text(size: 8pt, fill: muted)
  #grid(columns: (1fr, auto), [Umfragen · Auswertung #data.snapshotId.slice(0, 8)], [Seite #counter(page).display("1 / 1", both: true)])
])
#set text(font: "Libertinus Serif", size: 10pt, fill: ink, lang: "de")
#set par(leading: 0.55em)
#set heading(numbering: none)
#show heading.where(level: 1): set text(size: 19pt, fill: blue)
#show heading.where(level: 2): set text(size: 13pt, fill: blue)
#show heading.where(level: 3): set text(size: 10pt, weight: "bold")

#let header(..cells) = table.header(repeat: true, ..cells.pos().map(cell => table.cell(fill: blue, text(fill: white, weight: "bold", cell))))
#let field(label, value) = ([#label], [#value])
#let distribution(index, group) = {
  heading(level: 3, group.label)
  table(
    columns: (2fr, 1.4fr, auto, auto, auto),
    align: (left, left, right, right, right),
    inset: (x: 2mm, y: 2.5mm), stroke: (bottom: 0.5pt + border),
    table.header(repeat: true,
      table.cell(colspan: 5, fill: surface, text(size: 9pt)[Frage #index / #group.label]),
      ..([Antwort], [Anteil (0-100 %)], [Anzahl], [Basis], [%]).map(cell => table.cell(fill: blue, text(fill: white, weight: "bold", cell))),
    ),
    ..group.rows.map(row => (
      table.cell(breakable: row.label.len() > 1000)[#row.label],
      align(horizon, block(width: 100%, height: 3mm, fill: surface)[
        #block(width: row.percentage * 1%, height: 3mm, fill: blue)
      ]),
      [#row.count], [#row.denominator], [#row.percentageLabel],
    )).flatten(),
  )
}

#text(size: 10pt, fill: muted)[UMFRAGEN / AUSWERTUNG]
= #data.title
#text(fill: muted)[Version #data.versionNumber · #data.testData]
#v(5mm)
#block(fill: surface, inset: 5mm, width: 100%)[
  #text(size: 25pt, fill: blue, weight: "bold")[#data.participationCount]
  #h(3mm) ausgewählte Teilnahmen
  #v(2mm)
  #data.statuses
]

== Auswahl und Datenstand
#table(columns: (43mm, 1fr), inset: (x: 1mm, y: 1.6mm), stroke: none,
  ..field("Auswertung", data.snapshotId),
  ..field("Erstellt (UTC)", data.createdAt),
  ..field("Teilnahme ab (inkl.)", data.createdFrom),
  ..field("Teilnahme bis (exkl.)", data.createdBefore),
  ..field("Umfrage", data.surveyId),
  ..field("Fragebogenversion", data.versionId),
  ..field("SurveyJS / Profil", data.rendererVersion + " / " + data.capabilityProfile),
  ..field("Berichtsversion", data.renderVersion),
)

== Teilnahme im gewählten Zeitraum
Die folgenden Statuszahlen umfassen alle Teilnahmen dieser Fragebogenversion,
dieses Zeitraums und derselben Datenart. Die ausgewählte Statusmenge steht oben.
#table(columns: (1fr, auto), inset: 2mm, stroke: (bottom: 0.5pt + border),
  header([Status], [Teilnahmen]),
  ..data.statusCounts.map(item => ([#item.label], [#item.count])).flatten(),
)

== So sind die Zahlen zu lesen
Die Basis einer Antwortverteilung sind die gültig beantworteten Teilnahmen zur
jeweiligen Frage; bei Matrizen zählt jede Zeile für sich. Fehlende Antworten sind
keine Nullwerte. Mehrfachauswahlen können zusammen mehr als 100 % ergeben.
Ausgeblendete und ungültige Antworten sind gesondert ausgewiesen. Prozentwerte
und Kennzahlen sind auf höchstens zwei Nachkommastellen gerundet.
Dieser Bericht enthält keine einzelnen Antworten und keine Freitexte.

#pagebreak()
#for (index, q) in data.questions.enumerate() {
  block(breakable: false)[
    #heading(level: 2, [#(index + 1). #q.title])
    #v(2mm)
    #table(columns: (1fr, 1fr, 1fr, 1fr, 1fr), inset: 2mm, stroke: (bottom: 0.5pt + border),
      header([Relevant], [Beantwortet], [Unbeantwortet], [Ausgeblendet], [Ungültig]),
      [#q.relevant], [#q.answered], [#q.unanswered], [#q.hidden], [#q.invalid],
    )
  ]
  if q.metrics.len() > 0 {
    v(2mm)
    table(columns: (1fr, auto), inset: 2mm, stroke: none,
      ..q.metrics.map(metric => ([#metric.label], strong(metric.value))).flatten(),
    )
  }
  for group in q.groups { distribution(index + 1, group) }
  if q.matrixRows.len() > 0 {
    heading(level: 3, [Vollständigkeit der Matrix])
    table(columns: (1fr, auto, auto, auto), inset: 2mm, stroke: (bottom: 0.5pt + border),
      header([Zeile], [Beantwortet], [Unbeantwortet], [Ungültig]),
      ..q.matrixRows.map(row => ([#row.label], [#row.answered], [#row.unanswered], [#row.invalid])).flatten(),
    )
  }
  if q.kind in ("text", "comment") {
    v(2mm)
    text(fill: muted)[Freitexte werden ausschließlich in der berechtigten Einzelantwortansicht angezeigt.]
  }
  v(6mm)
}

== Zuletzt gespeicherte Seite
Diese Angaben beschreiben den letzten gespeicherten Stand der ausgewählten
Teilnahmen. Sie sind kein Nachweis dafür, auf welcher Seite jemand abgebrochen hat.
#table(columns: (1fr, auto), inset: 2mm, stroke: (bottom: 0.5pt + border),
  header([Seite], [Teilnahmen]),
  ..data.lastPages.map(page => ([#page.label], [#page.count])).flatten(),
)

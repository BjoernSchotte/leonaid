#let golden-invoice(
  number: "",
  status: "",
  amount: "",
  recipient: "",
  street: "",
  postal-code: "",
  city: "",
) = {
  set document(
    title: "Golden-Rechnung " + number,
    author: "LeonAid PoC",
    keywords: ("Golden Dataset v1", "synthetisch"),
  )
  set page(
    paper: "a4",
    margin: (x: 24mm, y: 22mm),
  )
  set text(size: 10pt, lang: "de")
  set par(leading: 0.65em)

  align(right)[
    #text(17pt, weight: "bold")[LeonAid]
    \
    Golden Dataset v1 · synthetische Testrechnung
  ]

  v(20mm)

  text(8pt, fill: rgb("#475569"))[
    LeonAid PoC · Teststraße 1 · 10115 Beispielstadt
  ]
  v(3mm)
  strong(recipient)
  linebreak()
  street
  linebreak()
  postal-code + " " + city

  v(20mm)

  text(16pt, weight: "bold")[
    Rechnung #number
  ]
  v(4mm)

  table(
    columns: (1fr, auto),
    inset: (x: 0pt, y: 4pt),
    stroke: (bottom: 0.5pt + rgb("#cbd5e1")),
    [Leistung], [Betrag],
    [Krapfenboxen der Charity-Aktion Krapfentaxi 2026], [#amount],
  )

  v(8mm)
  align(right)[
    #text(12pt, weight: "bold")[Gesamtbetrag: #amount]
  ]

  v(16mm)
  [
    Status im Golden Dataset: *#status*

    Dieses PDF ist ein deterministisches Testartefakt. Sämtliche Namen,
    Adressen und Beträge sind synthetisch und gehören zur reservierten
    Testumgebung `leonaid.invalid`.
  ]

  v(1fr)
  line(length: 100%, stroke: 0.5pt + rgb("#cbd5e1"))
  v(3mm)
  text(8pt, fill: rgb("#475569"))[
    LeonAid Proof of Concept · Dataset 1.0.0 · #number
  ]
}

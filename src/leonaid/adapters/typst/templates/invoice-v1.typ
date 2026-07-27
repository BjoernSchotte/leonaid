#let data = json("invoice.json")
#let blue = rgb("#00338d")
#let navy = rgb("#0d2240")
#let gold = rgb("#f2c94c")
#let ink = rgb("#172033")
#let muted = rgb("#667085")
#let border = rgb("#d8dee9")
#let surface = rgb("#f5f7fb")

#set document(
  title: data.title,
  author: data.issuer.legalName,
  keywords: ("LeonAid", "Rechnung", data.renderVersion),
)
#set page(
  paper: "a4",
  margin: (top: 18mm, bottom: 20mm, x: 20mm),
  footer: context [
    #set text(font: "Libertinus Serif", size: 7.5pt, fill: muted)
    #grid(
      columns: (1fr, auto),
      align: (left, right),
      [LeonAid · #data.number],
      [Seite #counter(page).display("1 / 1", both: true)],
    )
  ],
)
#set text(font: "Libertinus Serif", size: 9.5pt, fill: ink, lang: "de")
#set par(leading: 0.7em)

#grid(
  columns: (1fr, auto),
  align: (left, right),
  [
    #grid(
      columns: (12mm, 1fr),
      gutter: 4mm,
      align: horizon,
      box(
        width: 12mm,
        height: 12mm,
        fill: navy,
        radius: 3mm,
        align(center + horizon, text(fill: white, size: 15pt, weight: "bold")[L]),
      ),
      [
        #text(size: 14pt, weight: "bold", fill: navy)[LeonAid]
        #linebreak()
        #text(size: 8pt, fill: muted)[Gemeinsam Wirkung organisieren]
      ],
    )
  ],
  [
    #text(size: 24pt, weight: "bold", fill: navy)[Rechnung]
    #linebreak()
    #text(size: 9pt, fill: blue, weight: "bold")[#data.number]
  ],
)

#v(13mm)

#text(size: 7.5pt, fill: muted)[
  #data.issuer.legalName · #data.issuer.streetLine1 ·
  #data.issuer.postalCode #data.issuer.city
]
#v(2.5mm)
#block(width: 92mm, inset: (x: 0pt, y: 1.5mm))[
  #text(size: 11pt, weight: "bold")[#data.recipient.recipientName]
  #linebreak()
  #data.recipient.streetLine1
  #linebreak()
  #data.recipient.postalCode #data.recipient.city
  #linebreak()
  #data.recipient.countryCode
]

#v(9mm)

#grid(
  columns: (1fr, 58mm),
  gutter: 12mm,
  [
    #text(size: 16pt, weight: "bold", fill: navy)[Rechnung #data.number]
    #v(2mm)
    #text(fill: muted)[
      Vielen Dank für Ihre Unterstützung der Charity-Aktion.
      Die folgenden Leistungen wurden verbindlich vereinbart.
    ]
  ],
  block(
    fill: surface,
    radius: 2mm,
    inset: 4mm,
  )[
    #grid(
      columns: (1fr, auto),
      column-gutter: 4mm,
      row-gutter: 1.6mm,
      [Rechnungsdatum], [#data.issuedOn],
      [Leistungsdatum], [#data.serviceOn],
      [Fällig am], [#data.dueOn],
    )
  ],
)

#v(8mm)

#table(
  columns: (1fr, 20mm, 25mm, 28mm),
  align: (left, right, right, right),
  inset: (x: 2mm, y: 3mm),
  stroke: (bottom: 0.5pt + border),
  table.header(
    repeat: true,
    table.cell(fill: navy, text(fill: white, weight: "bold")[Beschreibung]),
    table.cell(fill: navy, text(fill: white, weight: "bold")[Menge]),
    table.cell(fill: navy, text(fill: white, weight: "bold")[Einzelpreis]),
    table.cell(fill: navy, text(fill: white, weight: "bold")[Gesamt]),
  ),
  ..data.lines.map(line => (
    [#line.description],
    [#line.quantity #line.unit],
    [#line.unitPrice],
    text(weight: "bold")[#line.gross],
  )).flatten(),
)

#v(6mm)

#align(right)[
  #block(width: 86mm, breakable: false)[
    #grid(
      columns: (1fr, auto),
      column-gutter: 4mm,
      row-gutter: 1.8mm,
      [Nettobetrag], [#data.net],
      [Umsatzsteuer], [#data.tax],
      grid.cell(
        colspan: 2,
        inset: (top: 2.5mm),
        stroke: (top: 1pt + navy),
      )[
        #grid(
          columns: (1fr, auto),
          column-gutter: 4mm,
          [#text(size: 12pt, weight: "bold", fill: navy)[Gesamtbetrag]],
          [#text(size: 12pt, weight: "bold", fill: navy)[#data.gross]],
        )
      ],
    )
  ]
]

#v(9mm)

#block(
  breakable: false,
  stroke: (left: 2pt + gold),
  inset: (left: 4mm, y: 2.5mm),
)[
  #text(weight: "bold", fill: navy)[Steuerhinweis]
  #linebreak()
  #data.taxNote
]

#v(7mm)

#block(
  breakable: false,
  fill: surface,
  radius: 2mm,
  inset: 4mm,
)[
  #text(weight: "bold", fill: navy)[Zahlung]
  #linebreak()
  Bitte überweisen Sie den Gesamtbetrag bis zum #data.dueOn unter Angabe der
  Zahlungsreferenz *#data.paymentReference*.
]

#v(9mm)

#grid(
  columns: (1fr, 1fr),
  gutter: 12mm,
  [
    #text(size: 8pt, weight: "bold", fill: navy)[Rechnungsaussteller]
    #linebreak()
    #data.issuer.legalName
    #linebreak()
    #data.issuer.streetLine1
    #linebreak()
    #data.issuer.postalCode #data.issuer.city
    #linebreak()
    #data.issuer.countryCode
  ],
  [
    #text(size: 8pt, weight: "bold", fill: navy)[Steuer- und Kontaktdaten]
    #linebreak()
    Steuer-ID: #data.issuer.taxIdentifier
    #linebreak()
    #data.issuer.email
  ],
)

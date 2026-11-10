#let data = json("document.json")
#let blue = rgb("#00338d")
#let navy = rgb("#0d2240")
#let gold = rgb("#f2c94c")
#let ink = rgb("#172033")
#let muted = rgb("#667085")
#let surface = rgb("#f5f7fb")

#set document(
  title: data.title,
  author: data.body.legalName,
  keywords: ("LeonAid", "Spendenzusage", data.renderVersion),
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
#set text(font: "Libertinus Serif", size: 10pt, fill: ink, lang: "de")
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
    #text(size: 24pt, weight: "bold", fill: navy)[Spendenzusage]
    #linebreak()
    #text(size: 9pt, fill: blue, weight: "bold")[#data.number]
  ],
)

#v(13mm)

#text(size: 7.5pt, fill: muted)[
  #data.body.legalName · #data.body.streetLine1 ·
  #data.body.postalCode #data.body.city
]
#v(2.5mm)
#block(width: 92mm, inset: (x: 0pt, y: 1.5mm))[
  #text(size: 11pt, weight: "bold")[#data.donor.name]
  #linebreak()
  #data.donor.streetLine1
  #linebreak()
  #data.donor.postalCode #data.donor.city
  #linebreak()
  #data.donor.countryCode
]

#v(9mm)

#grid(
  columns: (1fr, 58mm),
  gutter: 12mm,
  [
    #text(size: 16pt, weight: "bold", fill: navy)[#data.title]
  ],
  block(
    fill: surface,
    radius: 2mm,
    inset: 4mm,
  )[
    #grid(
      columns: (1fr, auto),
      column-gutter: 4mm,
      row-gutter: 2.2mm,
      [Datum], [#data.issuedOn],
      [Spende], [#text(weight: "bold")[#data.amount]],
    )
  ],
)

#v(6mm)

#data.thanks

#v(1mm)
#data.purpose

#v(7mm)

#block(
  breakable: false,
  fill: surface,
  radius: 2mm,
  inset: 4mm,
  width: 100%,
)[
  #text(weight: "bold", fill: navy)[Überweisung]
  #linebreak()
  #data.request
  #v(2mm)
  #grid(
    columns: (32mm, 1fr),
    column-gutter: 3mm,
    row-gutter: 2.2mm,
    [Betrag], [#text(weight: "bold")[#data.amount]],
    [Kontoinhaber], [#data.bank.accountHolder],
    [IBAN], [#data.bank.iban],
    ..if data.bank.bic != none {
      ([BIC], [#data.bank.bic])
    } else {
      ()
    },
    [Verwendungszweck], [#text(weight: "bold")[#data.bank.reference]],
  )
]

#v(7mm)

#block(
  breakable: false,
  stroke: (left: 2pt + gold),
  inset: (left: 4mm, y: 2.5mm),
)[
  #data.notice
]

#v(9mm)

#grid(
  columns: (1fr, 1fr),
  gutter: 12mm,
  [
    #text(size: 8pt, weight: "bold", fill: navy)[Empfänger der Spende]
    #linebreak()
    #data.body.legalName
    #linebreak()
    #data.body.streetLine1
    #linebreak()
    #data.body.postalCode #data.body.city
    #linebreak()
    #data.body.countryCode
  ],
  [
    #text(size: 8pt, weight: "bold", fill: navy)[Steuerdaten]
    #linebreak()
    #data.body.taxOffice
    #linebreak()
    Steuernummer: #data.body.taxNumber
  ],
)

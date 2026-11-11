#let data = json("document.json")
#let navy = rgb("#0d2240")
#let ink = rgb("#172033")
#let muted = rgb("#667085")
#let surface = rgb("#f5f7fb")
#let line-color = rgb("#98a2b3")

#set document(
  title: data.documentTitle,
  author: data.body.legalName,
  keywords: ("LeonAid", "Zuwendungsbestätigung", data.renderVersion),
)
#set page(
  paper: "a4",
  margin: (top: 18mm, bottom: 20mm, x: 20mm),
  footer: context [
    #set text(font: "Libertinus Serif", size: 7.5pt, fill: muted)
    #grid(
      columns: (1fr, auto),
      align: (left, right),
      [#data.number · zur Spende #data.donationNumber],
      [Seite #counter(page).display("1 / 1", both: true)],
    )
  ],
)
#set text(font: "Libertinus Serif", size: 10pt, fill: ink, lang: "de")
#set par(leading: 0.7em, justify: false)

// The issuer of the receipt is the receiving body: its name and address
// head the letter, as the official sample asks.
#text(size: 8pt, weight: "bold", fill: navy)[Aussteller]
#linebreak()
#text(size: 11pt, weight: "bold")[#data.body.legalName]
#linebreak()
#data.body.streetLine1, #data.body.postalCode #data.body.city

#v(9mm)

#text(size: 15pt, weight: "bold", fill: navy)[#data.title]
#v(1mm)
#text(size: 9pt)[#data.subtitle]

#v(2mm)
#text(size: 8.5pt, fill: muted)[Nummer #data.number]

#v(7mm)

#text(size: 8pt, weight: "bold", fill: navy)[Name und Anschrift des Zuwendenden]
#v(1mm)
#block(
  width: 100%,
  fill: surface,
  radius: 2mm,
  inset: 4mm,
)[
  #text(weight: "bold")[#data.donor.name]
  #linebreak()
  #data.donor.streetLine1
  #linebreak()
  #data.donor.postalCode #data.donor.city
  #linebreak()
  #data.donor.countryCode
]

#v(5mm)

#block(
  breakable: false,
  width: 100%,
  stroke: 0.6pt + line-color,
  radius: 2mm,
  inset: 4mm,
)[
  #grid(
    columns: (1.45fr, 2fr, 1fr),
    column-gutter: 5mm,
    [
      #text(size: 8pt, fill: muted)[Betrag der Zuwendung – in Ziffern –]
      #linebreak()
      #text(size: 12pt, weight: "bold")[#data.amount]
    ],
    [
      #text(size: 8pt, fill: muted)[– in Buchstaben –]
      #linebreak()
      #text(size: 11pt, weight: "bold")[#data.amountInWords]
    ],
    [
      #text(size: 8pt, fill: muted)[Tag der Zuwendung]
      #linebreak()
      #text(size: 12pt, weight: "bold")[#data.receivedOn]
    ],
  )
]

#v(5mm)

#data.noWaiver

#v(4mm)

#data.notice

#v(4mm)

#data.purpose

#v(11mm)

#block(breakable: false, width: 100%)[
  #if data.signedByMachine [
    #data.placeAndDate
    #linebreak()
    #text(weight: "bold")[#data.signatory]
    #v(2mm)
    #text(size: 8.5pt)[#data.signatureNote]
  ] else [
    #data.placeAndDate
    #v(13mm)
    #line(length: 85mm, stroke: 0.6pt + ink)
    #v(-1mm)
    #text(weight: "bold")[#data.signatory]
    #linebreak()
    #text(size: 8pt, fill: muted)[#data.signatureNote]
  ]
]

#v(9mm)

#block(
  breakable: false,
  width: 100%,
)[
  #set text(size: 8pt)
  #set par(leading: 0.6em)
  #data.liability
]

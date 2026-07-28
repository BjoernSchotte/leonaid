# ADR-0002: Steuer- und Rechnungsanforderungen als Scope-Stop

- Status: angenommen
- Datum: 2026-07-28
- Entscheider: Produktverantwortlicher und Implementierung
- Fachliche Entscheider: rechtlicher Träger und Steuerberatung
- Referenz: PoC ADR-0004 und Pilot-Entscheidungsregister

## Kontext

LeonAid erzeugt im PoC eine deterministische PDF-Rechnung aus einem
unveränderlichen Snapshot. Das ist weder eine vollständige Buchhaltung noch
automatisch eine strukturierte E-Rechnung. Steuerfall, Pflichtangaben und
E-Rechnungsbedarf hängen von der konkreten Installation und dem
Pilotzeitraum ab.

## Entscheidung

Der Pilot beginnt nur, wenn Träger, Steuerfall, Pflichtangaben,
Freigabeverantwortung und E-Rechnungsbedarf extern bestätigt sind.

Das Register akzeptiert für den Steuerfall nur `small_business`,
`standard_vat` oder `tax_exempt`. Ergibt die Prüfung
`full_accounting_required`, erhält die Entscheidung den Status `stop`.
Ergibt die E-Rechnungsprüfung `required`, erhält auch diese Entscheidung
`stop`.

Ein solcher Stop wird nicht als stilles Feature oder Konfigurationsdetail in
den Pilot gezogen. Zuerst braucht es einen eigenen Scope, Implementierungsplan
und fachliche Abnahme für Buchhaltung beziehungsweise XRechnung/ZUGFeRD.

## Konsequenzen

- Der synthetische Kleinunternehmerfall des Golden Dataset ist keine
  produktive Vorentscheidung.
- Typst bleibt PDF-Renderer, aber kein E-Rechnungsformat.
- Widersprüchliche Freigaben werden maschinell abgelehnt.
- Erst nach externer Freigabe werden konkrete Rechnungswerte über die
  vorgesehene Admin-Oberfläche gepflegt.


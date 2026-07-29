# Organisation & Recht konfigurieren

Stand: 28. Juli 2026

Dieses Runbook beschreibt die technische Pflege der installationsweiten
Träger-, Rechnungs- und Datenschutzgrundlage. Es ersetzt keine Rechts- oder
Steuerberatung. Reale Nachweisdokumente bleiben im privaten Evidence Store;
LeonAid speichert ausschließlich deren neutrale Evidence-ID.

## Fachlicher Schnitt

Die Admin-Seite **Organisation & Recht** unter `/admin/legal` enthält:

1. Träger- und Rechnungsausstellerdaten, Bankverbindung, Steuerfall,
   Rechnungsnummernformat und Zahlungsziel;
2. Rechtsgrundlage, Informationstext, Textversion, Datenschutzkontakt und
   Aufbewahrungsfristen;
3. die E-Rechnungsentscheidung und die zugehörigen Evidence-IDs.

Diese installationsweite Grundlage ist nicht dasselbe wie das
aktionsbezogene Rechnungsprofil. Das Rechnungsprofil einer Charity-Aktion
bleibt der heute aktive Vertrag für die konkrete Rechnungserzeugung. Es darf
erst dann mit realen Werten bestätigt werden, wenn die installationsweite
Grundlage fachlich aktiviert ist. Damit gibt es keine zweite, unkontrollierte
Quelle für bereits ausgestellte Rechnungssnapshots.

Betriebsdaten wie DNS, VPS, Mail-Relay, Backup-, Secret-, Monitoring- oder
Incident-Owner gehören nicht in dieses Formular. Sie werden über
Deployment-Konfiguration, Runbooks und das personenbezugsfreie
Entscheidungsregister geführt.

## Rollen und Freigabe

- Nur globale System-Admins dürfen die Konfiguration lesen oder verändern.
- Jede Änderung erzeugt eine neue unveränderliche Version.
- Der Ersteller kann seine eigene Version nicht freigeben.
- Eine zweite System-Administration hinterlegt eine neutrale
  Freigabe-Evidence-ID.
- Erst danach kann die Version verbindlich aktiviert werden.
- Schreibvorgänge verlangen einen frischen Login.
- Parallele oder veraltete Änderungen werden über die erwartete Revision
  abgewiesen.

Audit-Ereignisse enthalten Version, Revision und technische IDs, aber keine
IBAN, E-Mail-Adresse, Anschrift oder Rechtstexte.

## Sicherer Ablauf

1. Die fachlich verantwortlichen Rollen beantworten die Fragen aus
   `specs/leonaid-pilot/DECISION-INTAKE.md` und legen private Nachweise ab.
2. Eine System-Administration öffnet `/admin/legal`, pflegt alle drei
   geführten Schritte und kontrolliert die Zusammenfassung.
3. Sie speichert den Entwurf. Der Entwurf ist noch nicht wirksam.
4. Eine zweite System-Administration vergleicht Formular und privaten
   Nachweis, trägt dessen Evidence-ID ein und gibt den Entwurf frei.
5. Eine System-Administration aktiviert die freigegebene Version.
6. Die zuständigen Fachrollen prüfen anschließend den realen Staging-Beleg,
   das öffentliche Formular sowie Datenschutzexport und Löschworkflow.

Eine offene E-Rechnungsentscheidung blockiert die Aktivierung. Das Ergebnis
`required` blockiert den ERP-light-Piloten vollständig, weil XRechnung und
ZUGFeRD nicht stillschweigend in diesen Scope aufgenommen werden.

In einer Produktionsumgebung blockiert LeonAid außerdem erkennbare
Golden-/Test-/Platzhalterwerte wie `.invalid`, `.test`, `example.org`,
`golden` oder `review-required`.

## Reproduzierbarer technischer Nachweis

```sh
./leonaid test-pilot-legal-config
```

Der Befehl startet einen isolierten realen Compose-Stack mit PostgreSQL,
Twenty, RustFS und Chromium. Er prüft Rollen, unveränderliche Versionen,
Vier-Augen-Freigabe, Aktivierungssperren, konkurrierende Revisionen,
personenbezugsfreies Audit, Desktop-/Mobilbedienung und Accessibility. Nach
dem Lauf werden genau die Testcontainer, -netze und -volumes entfernt.

## Noch erforderliche Fachabnahme

Die technische Aktivierung allein schließt PILOT-044 nicht. Vor der
Produktivfreigabe müssen weiterhin:

- reale Träger-, Steuer-, Rechnungs- und Datenschutzwerte bestätigt werden;
- Public Form und Consent-Nachweis die aktive Textversion verwenden;
- Export und Erasure die aktivierten Fristen sowie Twenty-/RustFS-Referenzen
  berücksichtigen;
- ein realer Staging-Beleg durch die zuständige Fachperson abgenommen werden.


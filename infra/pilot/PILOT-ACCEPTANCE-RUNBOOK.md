# Pilot-Abnahme und Readiness-Dossier

Dieses Runbook führt technische Nachweise und ausdrückliche Entscheidungen
für `PILOT-053` zusammen. Es erteilt selbst keine fachliche, rechtliche oder
betriebliche Freigabe.

## Technischen Stand bewerten

Auf dem vorgesehenen Abschlusscommit:

```sh
./leonaid pilot-readiness --report .local/pilot/evidence/pilot-readiness.json
```

Der Report bewertet fail-closed:

- alle 21 Pilot-Tasks und ihre offenen Kriterien beziehungsweise
  Abhängigkeiten;
- alle 16 Hard-Gates und ihre zugeordneten Tasks;
- jeden reservierten Proof-Link als `missing`, `partial` oder `complete`;
- alle für `pilot-release` fälligen öffentlichen Entscheidungs-IDs;
- Branch, Commit, sauberen Arbeitsbaum und Gleichstand mit `origin/main`;
- eine kanonische SHA-256-Prüfsumme des vollständigen sanitizten Reports.

Exit `0` bedeutet technisch `ready`, Exit `2` `blocked`, Exit `3` eine
fachliche `stop`-Entscheidung und Exit `1` einen ungültigen Vertrag. Auch Exit
`0` ersetzt keine Unterschrift und keine explizite Go-Live-Entscheidung.

Der maschinenlesbare Report enthält nur öffentliche IDs, Status, Proof-Pfade
und Commit-SHAs. Private Pilot-Evidence, URLs, Zugangsdaten, Namen,
E-Mail-Adressen und Fachpayloads bleiben außerhalb des Reports.

## Abschlussprotokoll vorbereiten

Die Vorlage
[`PILOT-ACCEPTANCE-TEMPLATE.md`](PILOT-ACCEPTANCE-TEMPLATE.md) wird in den
privaten Evidence Store kopiert und dort ausgefüllt. Im Repository bleibt nur
die leere Vorlage.

Vor der Abnahme müssen mindestens referenziert sein:

1. Abschlusscommit und Release-Manifest;
2. Image- und Dependency-Locks;
3. Golden-Dataset-Version;
4. private Evidence-IDs ohne private URLs;
5. terminale CI-Läufe;
6. externer Restore-Nachweis;
7. sanitizte Screenshot- und Beleg-SHAs;
8. geltende Runbooks;
9. offene P2/P3 mit Owner und Termin;
10. Entscheidung zum nächsten Milestone und zum Betriebsübergang.

## Entscheidung

Produktverantwortung, Betrieb und die erforderlichen Fachrollen bestätigen
oder stoppen den Pilot ausdrücklich. Zulässige nächste Milestones sind:

- Krapfentaxi-Delivery;
- weiteres Pilothardening;
- Lions-Open-Discovery.

Eine erfolgreiche Pilotabnahme ist keine automatische unbefristete
Produktivfreigabe. Laufzeit, Nutzerkreis, Verantwortungsübergang, Betrieb,
Aufbewahrung und erneute Stopkriterien werden separat bestätigt.

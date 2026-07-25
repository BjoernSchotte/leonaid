# Entscheidungsvorlage: maicrm als Backend für LeonAid?

*Adressat: Björn (technisch, Mayflower) · Bezug: [`../architektur.md`](../architektur.md) · Stand: 2026-05-29*

> **Herkunft:** Code-Analyse des privaten Repos `github.com/mayflower/maicrm`
> (lokaler Klon: `~/opensrc/repos/github.com/mayflower/maicrm`, Stand-Push 2026-05-28)
> via Multi-Agent-Workflow — 7 parallele Capability-Reader über die Subsysteme,
> JTBD-Bewertung gegen `architektur.md`, abschließende Synthese mit Reife-/Betreibbarkeits-Check.
> maicrm ist die in `architektur.md` §14 geparkte „Mayflower-CRM-Klon"-Alternative.

## 1. TL;DR / Verdict

**maicrm passt nicht jetzt — bleibt aber korrekt die in §14 geparkte Alternative.** Fachlich
(Datenmodell, natives Owner-Scoping, eingebautes Lösch-Audit/DSGVO, echter Agenten-Runtime) ist
maicrm dem geplanten Twenty-Stack in mehreren Punkten überlegen. Der **eine entscheidende Grund
gegen einen Einsatz heute** ist Operability × Reife: maicrm ist Kubernetes-first (~25–31 Workloads,
~26 GB RAM-Baseline, geschätzt 450–700 €/Monat, 2–3 FTE SRE) **und** ein selbst-deklarierter
Prototyp („scaffold + service prototypes", 95 getrackte Gaps, davon 6 P0-blockierend, keine
Produktiv-Deployment-Evidenz). Das verletzt die harten Randbedingungen aus §1 (kein Budget,
Team = 2, eine ~10 €/Monat-Hetzner-VM, §8) frontal. Empfehlung: dem Plan exakt folgen (Twenty
hinter dem `CrmBackend`-Port validieren), die Agentik-Tür im Python-BFF nutzen — und maicrm erst
bei Single-Host-Deployment + geschlossenen P0-Gaps erneut prüfen.

## 2. Was maicrm ist

Event-sourced, AI-native CRM-Plattform aus dem Mayflower-Umfeld: ~25–31 Go-Microservices
(api-gateway, identity, tenant, crm-data, metadata, workflow, communication, eventaudit, policy …)
plus Python-LangGraph-Agenten-Runtime und Next.js-15-Frontend, auf PostgreSQL (pgvector/pgcrypto),
Contract-First mit generierten OpenAPI-/Event-/K8s-Artefakten und hash-verkettetem Audit-Log.
Explizit **Kubernetes-first — kein Docker-Compose-/Single-Binary-Pfad.** Reife ehrlich: bezeichnet
sich selbst als „scaffold + service prototypes", 95 offene Gaps (6 P0), keine
Produktiv-Deployment-/GitOps-/Backup-Restore-Evidenz. Twenty (v2.9.0 gepinnt) ist dagegen ein
laufendes, veröffentlichtes Produkt.

## 3. Fit je Use-Case

| Use-Case | Fit | Kernnutzen | Größtes Risiko |
|---|---|---|---|
| **Krapfentaxi** (verteilte Akquise) | **weak** | Fachlich voll: Custom Objects + per-Objekt-Status + **natives Row-Level-ABAC** (`workspace_id` + `workspace_member`-Join + `policy_owner`) erzwingt „A sieht nie B" in der DB — genau die §6.3-Lücke, die der Plan bei Twenty ins BFF auslagert. | Betrieb sprengt §1 um Faktor 30–100× (K8s-Pflicht, ~26 GB, „Not feasible"); Prototyp vs. laufendes Produkt. |
| **Datenpflege** (Import/Dedupe/aktuell halten) | **partial** | Stärkste Karte: Import mit Field-Mapping, 8-State-Lifecycle, Per-Row-Repair + **echtem Rollback**, native **Dedupe + ML-Review-Queue** — materiell sicherer als Twentys CSV-Import. | Import zielt laut Map **nur auf Standard-Objekte**, nicht auf Custom-Object „Sponsor" (ADR #4); **insert-only-mit-Dedupe, kein Upsert/Merge** → untergräbt „über Jahre aktuell halten". Plus K8s. |
| **Breitere Lions-Jobs** (Mitglieder, Events, Spenden, Reporting, Rollen) | **partial** | Datenmodell + Multi-Tenancy (Workspace=Club) + RBAC/ABAC + Audit-Substrat decken die Breite konzeptionell ab, teils eleganter als Twenty. | K.o. = Reife: 6 P0-Gaps, **keine** Lions-/Recurring-Workflows, **OIDC-only** (kein Senioren-Login, §4), Custom-Object-Coverage hinkt hinterher. |

## 4. Benefits gegenüber Twenty (wo maicrm uns echt schlägt)

Drei reale Punkte, die genau die heute ins BFF ausgelagerten Stellen treffen:

1. **Natives Record-Level-Authz statt Enterprise-gated RLP.** Owner-Scoping per
   `rowPolicyPredicates` direkt in der SQL-WHERE-Clause. **Schließt** §6.3 + ADR #2/#10 (Twentys
   RLP ist OSS-leer → Plan verlagert „A≠B" komplett ins BFF). *Einschränkung:* für Custom Objects
   (= Sponsor!) laut Map „incomplete".
2. **Event-sourciertes Lösch-Audit statt fehlendem Delete-Log.** Hash-verkettetes
   `audit.domain_event` mit expliziten `record.deleted`-Events, `RedactSubject` (Art. 17),
   Retention (Art. 5), Privacy-Export (Art. 15). **Schließt** §9 + ADR #11 (der verifizierte
   Twenty-Befund „loggt keine Löschungen, kein TTL, kein Export"). *Einschränkung:* GAP-016/GAP-004
   — Durabilität noch nicht abgenommen.
3. **Echter agentischer Runtime = unsere §14-Zukunft.** LangGraph mit `payload_generation`
   (+ `fact_checking`-Critic), `routing_orchestrator`, `context_compression`. **Schließt**
   §14-Wunschliste (Notiz zusammenfassen, „wen als Nächstes", Follow-ups). *Einschränkung:* genau
   die Lions-Funktionen sind als **Scaffolding/fehlend** markiert — wäre also selbst zu bauen, egal wo.

Auch praktisch stärker: **Import mit Staging+Rollback + native Dedupe/Match-Review-Queue** (deckt
die Datenpflege-Lücke und die in ADR #11 geplante Suppression-Logik).

## 5. Die harte Gegenrechnung (unbeschönigt)

**Kann ein 2-Personen-No-Budget-Verein ~25 Go-Microservices auf k8s betreiben? Nein.**

- **Betrieb:** Kubernetes-first ohne Ausweg. Minimal-Produktion: 3 Control-Plane + 6–8 Worker,
  ~26 GB RAM, 450–700 €/Monat, plus Argo CD/ExternalSecrets/Prometheus/PITR. Reader-Urteil wörtlich
  **„Not feasible"**, 80–120 Ops-h/Monat bzw. 2–3 FTE. §8 dagegen: **eine** Hetzner CX23/CX33,
  Docker Compose, ~6–15 €/Monat → Faktor **30–100×** daneben.
- **Reife:** selbst-deklarierter Prototyp, **6 P0-Gaps** (Persistenz teils in-memory/SQLite,
  Boundaries unvollständig, flache OpenAPI-Handler, Authz nicht an allen Entry-Points,
  Audit-Coupling lückig, keine verteilte Queue). Keine Releases/Live-Cluster/Restore-Evidenz.
  Jahre an Sponsoren-PII als einzige Kopie in einen unreleased Prototyp = für ein System of Record
  nicht verantwortbar.
- **Auth-Mismatch:** **OIDC-only**, kein Magic-Link → genau die §4/ADR-#3-Lücke. maicrm **entfernt
  das BFF nicht** (Senioren-Login bliebe nötig) → hier null Vorteil ggü. Twenty.
- **Vorteile treffen teils die falsche Objektklasse:** Row-Predicates **und** Import sind für
  Standard-Objekte fertig, für Custom Objects (= Sponsor) „incomplete" — zwei der drei
  Verkaufsargumente untergraben sich fürs konkrete Szenario selbst.

## 6. Empfehlung

**Dem Plan exakt folgen. maicrm bleibt §14-Alternative — heute nicht einlösen.**

1. **Twenty bleibt Backend für PoC/MVP**, validiert hinter dem `CrmBackend`/`CrmAdminBackend`-Port
   (§6.4, ADR #9). Der Port ist die billige Versicherung — kein Grund, sie jetzt zu ziehen.
2. **Agentik im Python-BFF nachrüsten, nicht das Backend tauschen** (`deepagents`/Anthropic-SDK,
   ADR #8) — genau wofür Python gewählt wurde.
3. **Ideen ernten, backend-unabhängig:** event-sourced Lösch-Audit (Vorbild Lösch-Log §9/ADR #11),
   Consent/Blocklist (Vorbild Suppression-List), Import-Staging + Dedupe-Review-Queue — landen
   ohnehin im `CrmAdminBackend`-Port.

**Wechsel zu maicrm — „swap IF" (alle Punkte):**

- **(a)** Single-Host-Deployment auf ~10 €-VM existiert (nicht K8s-Pflicht);
- **(b)** die 6 P0-Gaps geschlossen + released/deployed-Evidenz, insb. durchgängige
  PostgreSQL-Persistenz + Audit/Retention-Durabilität (GAP-004/016);
- **(c)** Custom-Object-Parität mit **Upsert/Merge** für Row-Authz **und** Import;
- **(d)** stabile API für die ~7 `CrmBackend`- + 3 `CrmAdminBackend`-Methoden;
- **(e)** konkreter Mehrwert über die validierte Twenty-Eignung hinaus.

Solange (a)–(c) nicht erfüllt sind, addiert maicrm nur Betriebsrisiko, ohne das BFF (Senioren-Login,
DSGVO-Logging) zu ersetzen. Der Backend-Port macht die spätere Neubewertung zu reiner Adapter-Arbeit
— das ist die ganze Absicht von ADR #9.

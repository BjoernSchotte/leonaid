# ADR-0010: OpenFeature mit LeonAid-eigenem PoC-Provider

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 6.1

## Kontext

LeonAid soll neue Funktionen kontrolliert aktivieren können, ohne
Berechtigungen mit Rollout-Entscheidungen zu vermischen oder Frontend und
Backend an das proprietäre Modell eines Feature-Flag-Anbieters zu binden.
Python/FastAPI und React benötigen dafür denselben Standard und konsistente
Flag-Schlüssel.

Ein zusätzlicher Flag-Management-Dienst würde im PoC einen weiteren
Betriebs-, Backup- und Ausfallpfad einführen. Gleichzeitig soll ein späterer
Wechsel zu `flagd`, OFREP oder einem anderen OpenFeature-Provider möglich
bleiben.

## Entscheidung

### OpenFeature ist die gemeinsame Auswertungsschnittstelle

Das FastAPI-Backend verwendet das offizielle Python-SDK
`openfeature-sdk==0.10.0`. Die React-Oberfläche verwendet das offizielle
`@openfeature/react-sdk@1.4.1` einschließlich seiner gelockten Web- und
Core-Abhängigkeiten.

Backend und Browser evaluieren ausschließlich katalogisierte, typisierte
Flag-Schlüssel. Unbekannte oder nicht verfügbare Flags fallen sicher auf den
im Code angegebenen Standardwert zurück.

### Der PoC hält den Verwaltungszustand in LeonAid PostgreSQL

Ein kleiner LeonAid-Provider implementiert den offiziellen
OpenFeature-Providervertrag. PostgreSQL ist die persistente Quelle für
Schaltzustand, Revision, Ändernde und Zeitpunkt. Der Provider wertet einen
atomar ersetzten Snapshot aus; Fach- und HTTP-Schichten kennen keine
Providerdetails.

Für den Browser liefert FastAPI nur client-sichere Auswertungen. Dort
übernimmt ein OpenFeature-In-Memory-Provider den vom Server gelieferten
Snapshot. Ein externer Flag-Dienst ist deshalb für den PoC nicht nötig. Der
Provider-Port bleibt so geschnitten, dass später ein OFREP-, `flagd`- oder
anderer OpenFeature-Provider eingesetzt werden kann.

### Verwaltung ist eine sicherheitskritische System-Admin-Aktion

Nur `system_admin` darf den katalogisierten Flag-Zustand lesen und ändern.
Änderungen benötigen eine frische Anmeldung, eine erwartete Revision und
erzeugen genau ein AuditEvent. Ein unveränderter Wert erzeugt weder eine neue
Revision noch einen neuen Audit-Eintrag.

Evaluation Context enthält im PoC nur eine opake User-ID, Rollen und die
Oberfläche `web` oder `pwa`. E-Mail, Name und andere personenbezogene
Attribute werden nicht an den Provider gegeben.

Feature-Flags steuern ausschließlich Rollout und Sichtbarkeit. Sie ersetzen
nie serverseitige Rollen-, Aktions- oder Datensatzberechtigungen. Ein
ausgeblendetes Frontend-Element macht einen Backend-Endpunkt nicht
unberechtigt erreichbar.

## PoC-Flags

| Schlüssel | Wirkung | Standard |
|---|---|---|
| `admin.preview_notice` | zeigt den internen PoC-Preview-Hinweis | aus |
| `admin.system_status_panel` | zeigt den Systemstatus und schaltet dessen zusätzlich geschützten Backend-Endpunkt frei | aus |

## Konsequenzen

- Python, React und eine spätere Tauri-Oberfläche verwenden dieselbe
  herstellerneutrale Auswertungssemantik.
- Der PoC erhält keinen zusätzlichen Infrastrukturservice und keine
  doppelte Benutzerverwaltung.
- Persistenz, Audit, Fresh Login und optimistische Konkurrenzkontrolle liegen
  vollständig im LeonAid Core.
- Ein späteres Targeting oder ein externer Provider ist möglich, benötigt
  aber eine eigene Datenschutz-, Betriebs- und Ausfallentscheidung.
- Entfernte oder dauerhaft aktivierte Flags müssen später katalogisiert
  bereinigt werden; Feature-Flags sind kein dauerhafter Ersatz für
  Produktentscheidungen.

# ADR-0003: Docker-basierter modularer FastAPI-Monolith

- Status: angenommen
- Datum: 2026-07-25
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 6

## Kontext

LeonAid benötigt transaktionale Fachlogik, HTTP-Clients, Worker und später
optional FastMCP-/LLM-Fähigkeiten. Web, PWA, Public Web und eine mögliche
Tauri-App sollen denselben fachlichen Kern verwenden.

## Entscheidung

Der Core ist ein modularer Python-Monolith mit FastAPI als dünnem
HTTP-Adapter, PostgreSQL als transaktionalem Store und dedizierten Workern für
durable Outbox-Jobs. React/TypeScript bedient Web und PWA; Astro bedient das
Public Web.

Twenty-, RustFS-, SMTP- und Typst-Zugriffe liegen hinter fachlichen Ports.
FastAPI-Routen, Astro Actions und Browser-Code enthalten keine maßgebliche
Fachlogik. Ein späterer FastMCP-Adapter ruft dieselben autorisierten
Application Services auf.

Alle PoC-Komponenten und sämtliche Tests laufen in Docker Compose. Auf dem
Host sind außer Docker, Git und den Repository-Befehlen keine
Projektlaufzeiten erforderlich.

## Konsequenzen

- OpenAPI ist der Clientvertrag.
- Externe Systeme bleiben austauschbar und exakt gepinnt.
- Autorisierung, Audit und Idempotenz gelten identisch für alle Adapter.
- Durable Effekte laufen nicht über FastAPI-`BackgroundTasks`.

## Nachtrag 2026-11-10: Suchindex der Sponsoren

Der Core hält keine Kopie von CRM-Firmen und -Personen. Einzige Ausnahme ist
`sponsor_search_entry` (specs/mails-documents-donations-push §9, D-S1): Name
und Ort der Parteien mit Akquise-Zuordnung, damit die Core-Suche Sponsoren
ohne CRM-Abfrage pro Tastendruck findet. Twenty bleibt maßgeblich; ein Worker
gleicht den Index per Polling und nächtlichem Volldurchlauf ab (D-S2).

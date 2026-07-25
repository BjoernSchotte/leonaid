# Managed Nextcloud für Vereine — Hosting-Recherche

*Stand: Mai 2026 · eigenständige Recherche (im Kontext des LeonAid-Projekts entstanden, aber
allgemein für Vereine nutzbar).*

> ℹ️ **Keine Gewähr.** Anbieter ändern Preise, Nutzerzahlen und Funktionen laufend — die
> konkreten Werte **vor einer Bestellung am jeweiligen Anbieter prüfen**. Quellen am Ende.

## Anwendungsfall & Kriterien

Ein Verein möchte Nextcloud als Kollaborations-/Datei-Plattform nutzen — Datei-Sharing, **Kalender,
Kontakte, Aufgaben**, **Collectives** (Wiki/„Collections"), **Deck** (Kanban), **Formulare**,
gemeinsame Dokumente (Collabora/OnlyOffice) und **optional Video-Conferencing** (Nextcloud Talk).

Kriterien dieser Recherche:

1. **App-Store-Apps über die Nextcloud-Oberfläche installierbar** (keine selbst entwickelten Plugins).
2. Möglichst **viele Nutzer** — idealerweise „beliebig viele", mindestens bis ~100.
3. **Optional Video-Conferencing.**
4. **EU/DSGVO** (bei personenbezogenen Daten Pflicht — vgl. die DSGVO-Gesprächsgrundlage des Projekts).

## Die zentrale Stolperfalle: Gruppen-Video braucht ein „HPB"

Nextcloud **Talk** macht 1:1- und Klein-Calls direkt per Peer-to-Peer (P2P). **Gruppen-Video** (mehr
als ein paar Teilnehmer) skaliert aber nur mit einem **High Performance Backend (HPB)** plus
TURN/STUN-Server. Viele managed Angebote (u. a. Hetzner Storage Share) stellen **kein HPB** bereit —
dort funktioniert Gruppen-Video nicht zuverlässig. **Das ist das Hauptunterscheidungsmerkmal.**

## Hetzner „Storage Share" (Baseline)

Vollständig managed (Updates, Backups mehrmals täglich, Monitoring, RAID/HA-DB), **DE/DSGVO**, kein
Mindestvertrag, **unbegrenzte Nutzer**.

- **Apps:** Kontakte, Kalender, Aufgaben sind **vorinstalliert** (standardmäßig aus, per Klick
  aktivierbar). Aus dem **App Store** selbst installierbar u. a. **Collectives, Deck, Forms,
  Collabora/OnlyOffice**.
- **Grenzen (ehrlich):** keine jeweils neueste Core-Version; nur **kuratierter `occ`-Subset** (keine
  Shell); **kein Hetzner-Support für selbst installierte Apps**.
- **Video:** ⚠️ **kein HPB** → nur Klein-Calls, kein verlässliches Gruppen-Video.
- **Preise:** NX11 1 TB ~**5 €**/Mon (3 Subdomains, 50 Verbindungen) · NX21 5 TB ~**14,19 € + USt.**
  (7 Subdomains, 100 Verbindungen) · NX31 10 TB (10 Subdomains, 200 Verbindungen).

→ **Bestes Preis-Leistungs-Angebot, solange kein Gruppen-Video nötig ist.**

## Andere managed Anbieter im Vergleich

| Anbieter | Land / DSGVO | Nutzer | App-Store-Install | Gruppen-Video (Talk + HPB) | Preis-Indikation |
|---|---|---|---|---|---|
| **NETWAYS (NWS)** | 🇩🇪 DE, ISO 27001 | keine künstliche Grenze; empfohlen ~5 / ~25 / **~100** | ja (Admin aktiviert App-Store-Apps) | **✅ HPB inklusive** (Advanced & Premium) | Basic €5,99 (50 GB) · **Advanced €49,99 (1 TB, HPB)** · **Premium €99,99 (2 TB, HPB)** /Mon |
| **Hetzner Storage Share** | 🇩🇪 DE | unbegrenzt | ja (eingeschränkt, kein Support) | ❌ kein HPB | ~5 € (1 TB) /Mon |
| **Stackhero** | 🇫🇷 EU | **unbegrenzt** (Nutzer + Apps) | ja | nicht bestätigt → prüfen | private Instanz; Preis am Anbieter prüfen |
| **Portknox** | 🇩🇪 DE | je Plan 1 / 5–10 / **10–50** / custom | „alle großen Apps" (Selbst-Install nicht explizit → prüfen) | **Add-on**: Talk-Signaling-Server ~**€119/Jahr** | Single €39 · Multi €79 · **Professional €179** /Jahr |
| **Cloud68.co** | 🇩🇪/EU | je Plan | ja (**Admin-Zugang**) | Talk möglich (HPB prüfen) | am Anbieter prüfen |
| **IONOS Managed Nextcloud** | 🇩🇪/EU, ISO 27001 | **min. 100 Nutzer** | ja (eigene Hilfeseite zu Apps) | Talk verfügbar | €37–100 **pro Nutzer/Jahr** (Enterprise-Zuschnitt) |
| **TAB.DIGITAL** | EU-only | (prüfen) | ja | (prüfen) | am Anbieter prüfen |

## Empfehlung nach Szenario

- **Kein / nur Klein-Video nötig** → **Hetzner Storage Share** (~5 €, unbegrenzte Nutzer, App-Store).
  Für „beliebig viele Nutzer + unbegrenzt Apps" alternativ **Stackhero** (FR/EU).
- **Gruppen-Video gewünscht** → **NETWAYS** ist der klare Treffer: DE/DSGVO, **HPB inklusive**, bis
  ~100 Nutzer, App-Store über Admin. Realistisch **Advanced €49,99/Mon (~25 Nutzer)** oder
  **Premium €99,99/Mon (~100 Nutzer)**. Alternativ **Portknox** (kleiner/flexibel, Talk-Server als
  ~€119/Jahr-Add-on).
- **IONOS** ist enterprise-zugeschnitten (**Mindestabnahme 100 Nutzer**, Pro-Nutzer-Preis) → für
  einen Verein meist preislich unattraktiv.

## Vor der Bestellung prüfen

- **App-Store-Selbstinstallation:** bei NETWAYS nicht explizit dokumentiert (Admin-App-Aktivierung
  ist bei managed Standard — kurz rückfragen). Bei Portknox/Stackhero ebenso konkret nachfragen.
- **Konkrete Wunsch-Apps** (z. B. eine bestimmte App-Version) gegen die unterstützte Core-Version
  abklären.
- **Gruppen-Video:** ob HPB enthalten ist und für wie viele Teilnehmer; vor Zusage **testen**.
- **DSGVO:** AV-Vertrag (Art. 28) des Anbieters, Serverstandort EU/DE, Backup-Konzept.
- **Nutzer-/Preisgrenzen** und Kündbarkeit (Mindestvertrag?).

## Quellen

- [Hetzner Storage Share](https://www.hetzner.com/storage/storage-share/) ·
  [Hetzner Docs — Storage Share General](https://docs.hetzner.com/storage/storage-share/general/) ·
  [Hetzner Docs — OCC Commands](https://docs.hetzner.com/storage/storage-share/configuration/occ-commands/)
- [NETWAYS Managed Nextcloud (Relaunch, HPB)](https://nws.netways.de/en/blog/2026/05/25/nextcloud-hosting-relaunched-more-storage-and-high-performance-backend/) ·
  [NETWAYS Managed Nextcloud](https://nws.netways.de/en/managed-services/managed-nextcloud/)
- [Portknox](https://portknox.net/en) · [Portknox Pricing](https://portknox.net/en/pricing)
- [Cloud68 Nextcloud](https://cloud68.co/managed-hosting/nextcloud)
- [IONOS — Apps in Managed Nextcloud](https://www.ionos.co.uk/help/cloud-storage/administration-of-the-managed-nextcloud/expanding-managed-nextclouds-capabilities-with-apps/)
- [Nextcloud Talk HPB (Hintergrund)](https://opensourceisfun.substack.com/p/nextcloud-talk-setting-up-a-hpb-high) ·
  [Nextcloud Admin Manual — Apps management](https://docs.nextcloud.com/server/stable/admin_manual/apps_management.html)
- [Nextcloud Provider-Verzeichnis](https://nextcloud.com/providers/) ·
  [HostAdvice: Nextcloud-Hoster](https://hostadvice.com/cloud-hosting/nextcloud-hosting/)

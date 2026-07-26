import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const appName = process.env.APP_NAME ?? "LeonAid";
const appKind = process.env.APP_KIND ?? "service";
const port = Number(process.env.PORT ?? "3000");
const webAssetDirectory = process.env.WEB_ASSET_DIR;
const pwaAssetDirectory = process.env.PWA_ASSET_DIR;
const coreApiUrl = process.env.CORE_API_URL ?? "http://api:8000";

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".webmanifest", "application/manifest+json; charset=utf-8"],
]);

function assetFile(requestUrl, assetDirectory, kind) {
  if (!assetDirectory || appKind !== kind) return undefined;
  const pathname = new URL(requestUrl, "http://localhost").pathname;
  let relative;
  if (kind === "web") {
    relative =
      pathname.startsWith("/assets/") || pathname === "/favicon.svg"
        ? pathname.slice(1)
        : pathname === "/" ||
            pathname === "/members" ||
            pathname === "/actions" ||
            pathname.startsWith("/actions/")
          ? "index.html"
          : undefined;
  } else {
    relative =
      pathname.startsWith("/assets/") ||
      pathname.startsWith("/icons/") ||
      pathname === "/manifest.webmanifest" ||
      pathname === "/sw.js" ||
      pathname === "/offline.html"
        ? pathname.slice(1)
        : pathname === "/offline"
          ? "offline.html"
          : pathname === "/" ||
              pathname === "/sponsors" ||
              pathname === "/activities"
            ? "index.html"
            : undefined;
  }
  if (!relative) return undefined;
  const root = path.resolve(assetDirectory);
  const candidate = path.resolve(root, relative);
  if (
    !candidate.startsWith(`${root}${path.sep}`) ||
    !fs.existsSync(candidate)
  ) {
    return undefined;
  }
  return candidate;
}

function webFile(requestUrl) {
  return assetFile(requestUrl, webAssetDirectory, "web");
}

function pwaFile(requestUrl) {
  return assetFile(requestUrl, pwaAssetDirectory, "pwa");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function applicationPage() {
  const configuration = JSON.stringify({ appKind, appName }).replaceAll(
    "<",
    "\\u003c",
  );
  return `<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <title>${escapeHtml(appName)}</title>
    <style>
      :root {
        color: #13233f;
        background: #f5f7fb;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-synthesis: none;
      }
      * { box-sizing: border-box; }
      body { margin: 0; min-width: 320px; min-height: 100vh; }
      button, a { font: inherit; }
      a { color: inherit; }
      .loading {
        min-height: 100vh;
        display: grid;
        place-items: center;
        color: #53627a;
      }
      .loading span {
        width: 2rem;
        height: 2rem;
        border: 3px solid #dce2ec;
        border-top-color: #d4a72c;
        border-radius: 999px;
        animation: spin .8s linear infinite;
      }
      @keyframes spin { to { transform: rotate(360deg); } }
      .shell { min-height: 100vh; display: grid; grid-template-columns: 17rem 1fr; }
      .sidebar {
        position: sticky;
        top: 0;
        height: 100vh;
        display: flex;
        flex-direction: column;
        padding: 1.25rem 1rem;
        color: #fff;
        background: #13233f;
      }
      .brand {
        display: flex;
        align-items: center;
        gap: .75rem;
        padding: .25rem .5rem 1.4rem;
        font-weight: 750;
        letter-spacing: -.02em;
      }
      .brand-mark {
        display: grid;
        width: 2.25rem;
        height: 2.25rem;
        place-items: center;
        color: #13233f;
        background: #e6bd4f;
        border-radius: .72rem;
        font-size: 1rem;
        font-weight: 850;
      }
      .nav-label {
        margin: .4rem .75rem .55rem;
        color: #aebbd0;
        font-size: .7rem;
        font-weight: 750;
        letter-spacing: .1em;
        text-transform: uppercase;
      }
      nav { display: grid; gap: .3rem; }
      .nav-item {
        display: flex;
        min-height: 2.75rem;
        align-items: center;
        gap: .7rem;
        padding: .68rem .75rem;
        border-radius: .7rem;
        color: #dce5f2;
        text-decoration: none;
      }
      .nav-item:hover, .nav-item:focus-visible {
        color: #fff;
        background: #243957;
        outline: 2px solid transparent;
      }
      .nav-item[aria-current="page"] {
        color: #fff;
        background: #2d4363;
        box-shadow: inset 3px 0 #e6bd4f;
      }
      .sidebar-context {
        margin-top: auto;
        padding: .9rem;
        border: 1px solid #314969;
        border-radius: .8rem;
        background: #192c49;
      }
      .sidebar-context small { display: block; color: #aebbd0; }
      .sidebar-context strong { display: block; margin-top: .25rem; font-size: .9rem; }
      main { min-width: 0; }
      .topbar {
        display: flex;
        min-height: 4.5rem;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        padding: .8rem clamp(1rem, 4vw, 2.4rem);
        border-bottom: 1px solid #dde3ed;
        background: rgba(255, 255, 255, .92);
      }
      .topbar-copy small { color: #697890; }
      .topbar-copy strong { display: block; margin-top: .15rem; }
      .roles { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .4rem; }
      .role {
        padding: .34rem .6rem;
        border: 1px solid #d5ddea;
        border-radius: 999px;
        color: #31415c;
        background: #fff;
        font-size: .78rem;
        font-weight: 650;
      }
      .content { max-width: 75rem; padding: clamp(1.25rem, 4vw, 2.5rem); }
      .eyebrow { color: #936f12; font-size: .75rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
      h1 { margin: .45rem 0 .5rem; color: #13233f; font-size: clamp(1.8rem, 4vw, 3rem); letter-spacing: -.04em; }
      .lead { max-width: 45rem; margin: 0; color: #617089; font-size: 1.04rem; line-height: 1.65; }
      .section-title { margin: 2.2rem 0 .8rem; font-size: 1rem; }
      .actions {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
        gap: .8rem;
      }
      .action-card {
        padding: 1rem;
        border: 1px solid #dfe5ee;
        border-radius: .85rem;
        background: #fff;
        box-shadow: 0 10px 28px rgba(19, 35, 63, .05);
      }
      .action-card strong { display: block; }
      .action-card span { display: block; margin-top: .35rem; color: #697890; font-size: .86rem; }
      .notice {
        max-width: 36rem;
        margin: 12vh auto;
        padding: 1.5rem;
        border: 1px solid #dfe5ee;
        border-radius: 1rem;
        background: #fff;
        box-shadow: 0 18px 44px rgba(19, 35, 63, .08);
      }
      .notice h1 { font-size: 1.6rem; }
      .notice p { color: #617089; line-height: 1.6; }
      .panel {
        max-width: 46rem;
        margin-top: 2rem;
        padding: clamp(1.1rem, 3vw, 1.6rem);
        border: 1px solid #dfe5ee;
        border-radius: 1rem;
        background: #fff;
        box-shadow: 0 12px 32px rgba(19, 35, 63, .06);
      }
      .form-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
      }
      .field { display: grid; gap: .4rem; }
      .field-wide { grid-column: 1 / -1; }
      label { color: #31415c; font-size: .82rem; font-weight: 720; }
      input, select, textarea {
        width: 100%;
        min-height: 2.85rem;
        padding: .65rem .75rem;
        border: 1px solid #cbd5e3;
        border-radius: .68rem;
        color: #13233f;
        background: #fff;
        font: inherit;
      }
      textarea { min-height: 6rem; resize: vertical; }
      input:focus, select:focus, textarea:focus {
        border-color: #8b6b19;
        outline: 3px solid rgba(230, 189, 79, .28);
      }
      .button {
        min-height: 2.85rem;
        padding: .68rem 1rem;
        border: 0;
        border-radius: .68rem;
        color: #13233f;
        background: #e6bd4f;
        font-weight: 780;
        cursor: pointer;
      }
      .button:disabled { cursor: wait; opacity: .58; }
      .button-secondary {
        min-height: 2.45rem;
        padding: .55rem .8rem;
        border: 1px solid #cbd5e3;
        border-radius: .65rem;
        color: #31415c;
        background: #fff;
        font-weight: 700;
        cursor: pointer;
      }
      .form-help, .form-status {
        color: #697890;
        font-size: .86rem;
        line-height: 1.5;
      }
      .form-status[data-state="success"] { color: #167044; }
      .form-status[data-state="error"] { color: #a33a2c; }
      .sponsor-layout {
        display: grid;
        grid-template-columns: minmax(0, 1.05fr) minmax(18rem, .95fr);
        gap: 1.1rem;
        align-items: start;
        margin-top: 2rem;
      }
      .sponsor-layout .panel { max-width: none; margin-top: 0; }
      .segment {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: .3rem;
        padding: .3rem;
        border: 1px solid #dfe5ee;
        border-radius: .78rem;
        background: #f3f5f9;
      }
      .segment button {
        min-height: 2.55rem;
        border: 0;
        border-radius: .56rem;
        color: #617089;
        background: transparent;
        font: inherit;
        font-weight: 740;
        cursor: pointer;
      }
      .segment button[aria-pressed="true"] {
        color: #13233f;
        background: #fff;
        box-shadow: 0 2px 8px rgba(19, 35, 63, .1);
      }
      .form-actions {
        display: flex;
        flex-wrap: wrap;
        gap: .6rem;
        align-items: center;
      }
      .result-empty {
        display: grid;
        min-height: 18rem;
        place-items: center;
        padding: 2rem;
        color: #697890;
        text-align: center;
      }
      .result-empty strong {
        display: block;
        margin-bottom: .35rem;
        color: #31415c;
      }
      .result-heading {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: .8rem;
        margin-bottom: 1rem;
      }
      .result-heading h2 { margin: 0; font-size: 1.1rem; }
      .match-badge {
        flex: none;
        padding: .3rem .55rem;
        border-radius: 999px;
        color: #166044;
        background: #e7f5ee;
        font-size: .72rem;
        font-weight: 780;
      }
      .candidate-list { display: grid; gap: .7rem; }
      .candidate {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: .75rem;
        padding: .9rem;
        border: 1px solid #dfe5ee;
        border-radius: .78rem;
        background: #fafbfd;
      }
      .candidate[data-selected="true"] {
        border-color: #b78a1f;
        background: #fffaf0;
        box-shadow: 0 0 0 2px rgba(230, 189, 79, .18);
      }
      .candidate input {
        width: 1.05rem;
        min-height: auto;
        margin-top: .18rem;
      }
      .candidate strong { display: block; }
      .candidate-meta {
        display: flex;
        flex-wrap: wrap;
        gap: .25rem .8rem;
        margin-top: .32rem;
        color: #697890;
        font-size: .82rem;
      }
      .assignment-warning {
        grid-column: 2;
        margin-top: .55rem;
        padding: .65rem .72rem;
        border: 1px solid #ebd28f;
        border-radius: .6rem;
        color: #725611;
        background: #fff8e5;
        font-size: .82rem;
        line-height: 1.45;
      }
      .preserve-note {
        margin: .8rem 0 0;
        color: #697890;
        font-size: .8rem;
        line-height: 1.5;
      }
      .success-card {
        padding: 1rem;
        border: 1px solid #a9dbc3;
        border-radius: .8rem;
        color: #145a3d;
        background: #effaf5;
      }
      .success-card strong { display: block; margin-bottom: .3rem; }
      .activity-layout {
        display: grid;
        grid-template-columns: minmax(20rem, .88fr) minmax(24rem, 1.12fr);
        gap: 1.1rem;
        align-items: start;
        margin-top: 2rem;
      }
      .activity-layout .panel { max-width: none; margin-top: 0; }
      .field-description {
        margin: -.15rem 0 .1rem;
        color: #7a879b;
        font-size: .78rem;
        font-weight: 500;
        line-height: 1.45;
      }
      .field-meta {
        display: flex;
        justify-content: space-between;
        gap: .75rem;
      }
      .character-count { color: #8793a5; font-size: .74rem; font-weight: 600; }
      .reminder-summary {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: .55rem;
        margin-bottom: 1rem;
      }
      .summary-tile {
        padding: .75rem;
        border: 1px solid #dfe5ee;
        border-radius: .72rem;
        background: #f8fafc;
      }
      .summary-tile strong {
        display: block;
        color: #13233f;
        font-size: 1.35rem;
        letter-spacing: -.03em;
      }
      .summary-tile span { color: #697890; font-size: .76rem; }
      .summary-tile[data-urgency="overdue"] {
        border-color: #efc2b9;
        background: #fff5f2;
      }
      .summary-tile[data-urgency="overdue"] strong { color: #9c392c; }
      .summary-tile[data-urgency="today"] {
        border-color: #ebd28f;
        background: #fff9e9;
      }
      .summary-tile[data-urgency="today"] strong { color: #725611; }
      .reminder-list, .activity-timeline { display: grid; gap: .65rem; }
      .reminder-card {
        display: grid;
        width: 100%;
        grid-template-columns: auto minmax(0, 1fr) auto;
        gap: .7rem;
        align-items: start;
        padding: .8rem;
        border: 1px solid #dfe5ee;
        border-radius: .78rem;
        color: #31415c;
        background: #fff;
        text-align: left;
        cursor: pointer;
      }
      .reminder-card:hover, .reminder-card:focus-visible {
        border-color: #b78a1f;
        outline: 3px solid rgba(230, 189, 79, .22);
      }
      .urgency-dot {
        width: .65rem;
        height: .65rem;
        margin-top: .28rem;
        border-radius: 999px;
        background: #9aa7b9;
      }
      .urgency-dot[data-urgency="overdue"] { background: #c14a38; }
      .urgency-dot[data-urgency="today"] { background: #d3a72f; }
      .urgency-dot[data-urgency="upcoming"] { background: #407cca; }
      .reminder-copy strong, .timeline-card strong { display: block; color: #13233f; }
      .reminder-copy span {
        display: block;
        margin-top: .2rem;
        color: #697890;
        font-size: .8rem;
        line-height: 1.4;
      }
      .reminder-date {
        padding: .25rem .45rem;
        border-radius: 999px;
        color: #52627a;
        background: #eef2f7;
        font-size: .7rem;
        font-weight: 760;
        white-space: nowrap;
      }
      .timeline-section { margin-top: 1.35rem; }
      .timeline-card {
        position: relative;
        padding: .85rem .9rem .85rem 1rem;
        border-left: 3px solid #d9b443;
        border-radius: 0 .72rem .72rem 0;
        background: #f8fafc;
      }
      .timeline-meta {
        display: flex;
        flex-wrap: wrap;
        gap: .25rem .75rem;
        margin-top: .28rem;
        color: #697890;
        font-size: .76rem;
      }
      .timeline-note {
        margin: .55rem 0 0;
        color: #40506a;
        font-size: .84rem;
        line-height: 1.5;
        white-space: pre-wrap;
      }
      .timeline-next {
        margin-top: .55rem;
        padding-top: .55rem;
        border-top: 1px solid #dfe5ee;
        color: #52627a;
        font-size: .78rem;
      }
      .empty-state {
        padding: 1.1rem;
        border: 1px dashed #cbd5e3;
        border-radius: .78rem;
        color: #697890;
        background: #fafbfd;
        font-size: .84rem;
        line-height: 1.5;
        text-align: center;
      }
      [hidden] { display: none !important; }
      fieldset {
        min-width: 0;
        margin: 0;
        padding: 1rem;
        border: 1px solid #dfe5ee;
        border-radius: .8rem;
      }
      legend { padding: 0 .35rem; font-weight: 760; }
      .choice-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .65rem; }
      .choice {
        display: flex;
        min-height: 2.7rem;
        align-items: center;
        gap: .55rem;
        padding: .55rem .65rem;
        border: 1px solid #dfe5ee;
        border-radius: .65rem;
      }
      .choice input { width: 1.1rem; min-height: auto; }
      .beneficiary-list { display: grid; gap: .8rem; }
      .beneficiary-row {
        display: grid;
        grid-template-columns: minmax(12rem, .8fr) minmax(16rem, 1.2fr);
        gap: .8rem;
        padding: .9rem;
        border: 1px solid #dfe5ee;
        border-radius: .8rem;
        background: #f9fafc;
      }
      .mobile-nav { display: none; }
      @media (max-width: 760px) {
        .shell { display: block; padding-bottom: 5rem; }
        .sidebar { display: none; }
        .topbar { align-items: flex-start; }
        .roles { max-width: 55%; }
        .content { padding-top: 1.5rem; }
        .form-grid { grid-template-columns: 1fr; }
        .field-wide { grid-column: auto; }
        .choice-grid, .beneficiary-row { grid-template-columns: 1fr; }
        .sponsor-layout { grid-template-columns: 1fr; }
        .activity-layout { grid-template-columns: 1fr; }
        .reminder-summary { grid-template-columns: repeat(3, minmax(4.5rem, 1fr)); }
        .result-empty { min-height: 10rem; }
        .mobile-nav {
          position: fixed;
          z-index: 2;
          right: .65rem;
          bottom: .65rem;
          left: .65rem;
          display: grid;
          grid-auto-columns: minmax(5rem, 1fr);
          grid-auto-flow: column;
          gap: .25rem;
          padding: .4rem;
          overflow-x: auto;
          border: 1px solid #d9e0eb;
          border-radius: 1rem;
          background: rgba(255, 255, 255, .96);
          box-shadow: 0 12px 35px rgba(19, 35, 63, .16);
        }
        .mobile-nav .nav-item {
          flex-direction: column;
          justify-content: center;
          min-height: 2.8rem;
          padding: .45rem .25rem;
          color: #31415c;
          font-size: .7rem;
          gap: .2rem;
          line-height: 1.15;
          text-align: center;
          white-space: normal;
        }
        .mobile-nav .nav-item[aria-current="page"] {
          color: #13233f;
          background: #f2e7c8;
          box-shadow: none;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .loading span { animation: none; }
      }
    </style>
  </head>
  <body>
    <div id="root" class="loading" aria-live="polite">
      <span aria-hidden="true"></span><p>Arbeitsbereich wird geladen …</p>
    </div>
    <script>
      const configuration = ${configuration};
      const root = document.querySelector("#root");

      const escapeHtml = (value) => String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

      function navMarkup(items, className) {
        return '<nav class="' + className + '" aria-label="Hauptnavigation">' +
          items.map((item) => {
            const rootPath = item.href.endsWith("/");
            const current = rootPath
              ? window.location.pathname === item.href
              : window.location.pathname.startsWith(item.href);
            return '<a class="nav-item" data-nav-key="' + escapeHtml(item.key) +
              '" href="' + escapeHtml(item.href) + '"' +
              (current ? ' aria-current="page"' : '') + '>' +
              '<span aria-hidden="true">◆</span><span>' +
              escapeHtml(item.label) + '</span></a>';
          }).join("") + '</nav>';
      }

      function dashboardMarkup(identity, surface) {
        const memberships = identity.actionMemberships;
        return '<p class="eyebrow">' + (surface === "pwa" ? "Akquise" : "Verwaltung") + '</p>' +
          '<h1>Guten Tag, ' + escapeHtml(identity.displayName.split(" ")[0]) + '.</h1>' +
          '<p class="lead">Hier findest du genau die Bereiche und Charity-Aktionen, für die du freigeschaltet bist.</p>' +
          '<h2 class="section-title">Deine Charity-Aktionen</h2>' +
          '<div class="actions" data-testid="action-list">' +
            (memberships.length > 0 ? memberships.map((membership) =>
              '<article class="action-card" data-action-id="' + escapeHtml(membership.actionId) + '">' +
                '<strong>' + escapeHtml(membership.actionName) + '</strong>' +
                '<span>' + escapeHtml(membership.roleLabel) + '</span>' +
              '</article>'
            ).join("") : '<article class="action-card"><strong>Noch keine Aktion</strong>' +
              '<span>Für dieses Konto ist derzeit keine Charity-Aktion freigeschaltet.</span></article>') +
          '</div>';
      }

      function invitationMarkup() {
        return '<p class="eyebrow">Mitglieder</p>' +
          '<h1>Mitglied einladen</h1>' +
          '<p class="lead">Versende einen einmaligen Magic Link und einen sechsstelligen Code für eine von dir verwaltete Charity-Aktion.</p>' +
          '<section class="panel" aria-labelledby="invite-heading">' +
            '<h2 id="invite-heading" class="section-title">Neue Einladung</h2>' +
            '<form id="invitation-form" class="form-grid">' +
              '<div class="field field-wide"><label for="invite-action">Charity-Aktion</label>' +
                '<select id="invite-action" data-testid="invite-action" name="actionId" required disabled>' +
                  '<option value="">Aktionen werden geladen …</option></select></div>' +
              '<div class="field"><label for="invite-name">Name</label>' +
                '<input id="invite-name" name="displayName" autocomplete="name" maxlength="160" required></div>' +
              '<div class="field"><label for="invite-email">Login-E-Mail</label>' +
                '<input id="invite-email" name="email" type="email" autocomplete="email" required></div>' +
              '<div class="field field-wide"><label for="invite-role">Rolle in dieser Aktion</label>' +
                '<select id="invite-role" data-testid="invite-role" name="role" required disabled>' +
                  '<option value="">Rollen werden geladen …</option></select></div>' +
              '<p class="form-help field-wide">Die Einladung gilt sofort nach Annahme. Die Login-E-Mail kann im PoC anschließend nicht selbst geändert werden.</p>' +
              '<button class="button field-wide" data-testid="invite-submit" type="submit" disabled>Einladung senden</button>' +
              '<p id="invitation-status" class="form-status field-wide" role="status" aria-live="polite"></p>' +
            '</form>' +
          '</section>';
      }

      function actionCreationMarkup() {
        const capabilities = [
          ["acquisition", "Akquise"],
          ["offerings", "Angebote"],
          ["ordering", "Bestellungen"],
          ["invoicing", "Rechnungen"],
        ];
        return '<p class="eyebrow">Charity-Aktionen</p>' +
          '<h1>Neue Aktion anlegen</h1>' +
          '<p class="lead">Lege den neutralen fachlichen Kern an. Aktionsspezifische Angebote und Formulare folgen getrennt.</p>' +
          '<section class="panel" aria-labelledby="action-heading">' +
            '<h2 id="action-heading" class="section-title">Grunddaten</h2>' +
            '<form id="action-form" class="form-grid">' +
              '<div class="field field-wide"><label for="action-name">Name der Aktion</label>' +
                '<input id="action-name" data-testid="action-name" name="name" maxlength="200" required></div>' +
              '<div class="field"><label for="action-carrier">Träger</label>' +
                '<input id="action-carrier" data-testid="action-carrier" name="carrierName" maxlength="200" required></div>' +
              '<div class="field"><label for="action-slug">Archiv-Slug</label>' +
                '<input id="action-slug" data-testid="action-slug" name="archiveSlug" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" maxlength="160" required></div>' +
              '<div class="field field-wide"><label for="action-purpose">Zweck</label>' +
                '<textarea id="action-purpose" data-testid="action-purpose" name="purpose" maxlength="2000" required></textarea></div>' +
              '<div class="field"><label for="action-start">Beginn</label>' +
                '<input id="action-start" data-testid="action-start" name="startsOn" type="date" required></div>' +
              '<div class="field"><label for="action-end">Ende</label>' +
                '<input id="action-end" data-testid="action-end" name="endsOn" type="date" required></div>' +
              '<fieldset class="field-wide"><legend>Funktionen</legend><div class="choice-grid">' +
                capabilities.map(([value, label]) =>
                  '<label class="choice"><input type="checkbox" name="capability" value="' +
                    value + '"><span>' + label + '</span></label>'
                ).join("") +
              '</div></fieldset>' +
              '<div class="field"><label for="action-goal">Zielwert</label>' +
                '<input id="action-goal" data-testid="action-goal" name="goalValue" inputmode="decimal" required></div>' +
              '<div class="field"><label for="action-unit">Einheit</label>' +
                '<input id="action-unit" data-testid="action-unit" name="unit" maxlength="40" required></div>' +
              '<div class="field"><label for="action-actual">Ist-Wert</label>' +
                '<input id="action-actual" data-testid="action-actual" name="actualValue" inputmode="decimal" value="0" required></div>' +
              '<div class="field"><label for="action-currency">Währung (optional)</label>' +
                '<input id="action-currency" data-testid="action-currency" name="currency" pattern="[A-Z]{3}" maxlength="3"></div>' +
              '<fieldset class="field-wide"><legend>Begünstigte</legend>' +
                '<div id="beneficiary-list" class="beneficiary-list"></div>' +
                '<button class="button-secondary" data-testid="add-beneficiary" type="button">Weiteren Begünstigten hinzufügen</button>' +
              '</fieldset>' +
              '<p class="form-help field-wide">Die Aktion startet als Entwurf. Mindestens ein Begünstigter ist erforderlich.</p>' +
              '<button class="button field-wide" data-testid="action-submit" type="submit">Aktion als Entwurf anlegen</button>' +
              '<p id="action-status" class="form-status field-wide" role="status" aria-live="polite"></p>' +
            '</form>' +
          '</section>';
      }

      function sponsorMarkup(identity) {
        const memberships = identity.actionMemberships.filter(
          (membership) => membership.role === "acquirer",
        );
        const options = memberships.map((membership) =>
          '<option value="' + escapeHtml(membership.actionId) + '">' +
          escapeHtml(membership.actionName) + '</option>'
        ).join("");
        return '<p class="eyebrow">Sponsor-Akquise</p>' +
          '<h1>Sponsor erfassen</h1>' +
          '<p class="lead">Prüfe zuerst den CRM-Bestand. LeonAid zeigt dir vorhandene Zuständigkeiten, bevor du einen Sponsor zusätzlich übernimmst.</p>' +
          '<div class="sponsor-layout">' +
            '<section class="panel" aria-labelledby="sponsor-form-heading">' +
              '<div class="result-heading"><div><h2 id="sponsor-form-heading">Wen möchtest du ansprechen?</h2>' +
                '<p class="form-help">Firma ist der führende Matchschlüssel. Ohne Firma werden Vor- und Nachname verwendet.</p></div></div>' +
              '<form id="sponsor-form" class="form-grid">' +
                '<div class="field field-wide"><label for="sponsor-action">Charity-Aktion</label>' +
                  '<select id="sponsor-action" name="actionId" data-testid="sponsor-action" required>' +
                    options + '</select></div>' +
                '<div class="segment field-wide" role="group" aria-label="Sponsorart">' +
                  '<button type="button" data-sponsor-mode="company" aria-pressed="true">Firma</button>' +
                  '<button type="button" data-sponsor-mode="person" aria-pressed="false">Privatperson</button>' +
                '</div>' +
                '<div class="field field-wide" data-company-field><label for="sponsor-company">Firmenname</label>' +
                  '<input id="sponsor-company" data-testid="sponsor-company" name="companyName" autocomplete="organization" maxlength="300" required></div>' +
                '<div class="field" data-person-field><label for="sponsor-given-name">Vorname</label>' +
                  '<input id="sponsor-given-name" name="givenName" autocomplete="given-name" maxlength="200"></div>' +
                '<div class="field" data-person-field><label for="sponsor-family-name">Nachname</label>' +
                  '<input id="sponsor-family-name" name="familyName" autocomplete="family-name" maxlength="200"></div>' +
                '<div class="field field-wide"><label for="sponsor-email">E-Mail <span class="form-help">(optional)</span></label>' +
                  '<input id="sponsor-email" name="email" type="email" autocomplete="email" maxlength="320"></div>' +
                '<div class="field field-wide" data-company-field><label for="sponsor-street">Straße <span class="form-help">(optional)</span></label>' +
                  '<input id="sponsor-street" name="streetLine1" autocomplete="street-address" maxlength="300"></div>' +
                '<div class="field" data-company-field><label for="sponsor-postal-code">PLZ <span class="form-help">(optional)</span></label>' +
                  '<input id="sponsor-postal-code" name="postalCode" autocomplete="postal-code" maxlength="40"></div>' +
                '<div class="field" data-company-field><label for="sponsor-city">Ort <span class="form-help">(optional)</span></label>' +
                  '<input id="sponsor-city" name="city" autocomplete="address-level2" maxlength="200"></div>' +
                '<div class="form-actions field-wide">' +
                  '<button class="button" data-testid="sponsor-preview" type="submit">Im CRM prüfen</button>' +
                '</div>' +
                '<p id="sponsor-status" class="form-status field-wide" role="status" aria-live="polite"></p>' +
              '</form>' +
            '</section>' +
            '<section class="panel" aria-labelledby="sponsor-result-heading">' +
              '<div id="sponsor-result" class="result-empty">' +
                '<div><strong id="sponsor-result-heading">Noch keine Prüfung</strong>' +
                '<span>Nach der CRM-Prüfung siehst du hier Treffer, Zusatzdaten und vorhandene Akquisiteure.</span></div>' +
              '</div>' +
            '</section>' +
          '</div>';
      }

      function activityMarkup(identity) {
        const memberships = identity.actionMemberships.filter(
          (membership) => membership.role === "acquirer",
        );
        const options = memberships.map((membership) =>
          '<option value="' + escapeHtml(membership.actionId) + '">' +
          escapeHtml(membership.actionName) + '</option>'
        ).join("");
        return '<p class="eyebrow">Akquise-Verlauf</p>' +
          '<h1>Aktivitäten & Wiedervorlagen</h1>' +
          '<p class="lead">Halte ein Gespräch in einem Schritt fest. LeonAid aktualisiert den Sponsorstatus und bringt fällige nächste Schritte nach vorn.</p>' +
          '<div class="activity-layout">' +
            '<section class="panel" aria-labelledby="activity-form-heading">' +
              '<div class="result-heading"><div>' +
                '<h2 id="activity-form-heading">Was ist passiert?</h2>' +
                '<p class="form-help">Wähle einen deiner Sponsoren und dokumentiere nur die Information, die für die weitere Akquise nötig ist.</p>' +
              '</div></div>' +
              '<form id="activity-form" class="form-grid">' +
                '<div class="field field-wide"><label for="activity-action">Charity-Aktion</label>' +
                  '<p id="activity-action-help" class="field-description">Die Aktion bestimmt, welche eigenen Sponsoren zur Auswahl stehen.</p>' +
                  '<select id="activity-action" name="actionId" aria-describedby="activity-action-help" required>' +
                    options + '</select></div>' +
                '<div class="field field-wide"><label for="activity-party">Sponsor</label>' +
                  '<p id="activity-party-help" class="field-description">Nur aktuell dir zugeordnete Firmen und Kontakte werden angezeigt.</p>' +
                  '<select id="activity-party" name="party" aria-describedby="activity-party-help" data-testid="activity-party" required disabled>' +
                    '<option value="">Sponsoren werden geladen …</option></select></div>' +
                '<div class="field"><label for="activity-channel">Kontaktweg</label>' +
                  '<p id="activity-channel-help" class="field-description">Wie der Kontakt stattgefunden hat.</p>' +
                  '<select id="activity-channel" name="channel" aria-describedby="activity-channel-help" required>' +
                    '<option value="phone">Telefon</option>' +
                    '<option value="email">E-Mail</option>' +
                    '<option value="in_person">Persönlich</option>' +
                  '</select></div>' +
                '<div class="field"><label for="activity-outcome">Ergebnis</label>' +
                  '<p id="activity-outcome-help" class="field-description">Der aktuelle Stand nach diesem Kontakt.</p>' +
                  '<select id="activity-outcome" name="outcome" aria-describedby="activity-outcome-help" required>' +
                    '<option value="reached">Erreicht</option>' +
                    '<option value="no_answer">Nicht erreicht</option>' +
                    '<option value="interested">Interesse</option>' +
                    '<option value="follow_up">Später nachfassen</option>' +
                    '<option value="committed">Zusage</option>' +
                    '<option value="declined">Absage</option>' +
                  '</select></div>' +
                '<div class="field field-wide"><div class="field-meta">' +
                    '<label for="activity-note">Kurze Notiz <span class="form-help">(optional)</span></label>' +
                    '<span id="activity-note-count" class="character-count">0 / 2.000</span></div>' +
                  '<p id="activity-note-help" class="field-description">Sachlich und knapp; keine privaten oder besonders sensiblen Angaben notieren.</p>' +
                  '<textarea id="activity-note" name="note" maxlength="2000" aria-describedby="activity-note-help activity-note-count" placeholder="Zum Beispiel: Angebot per E-Mail gewünscht."></textarea></div>' +
                '<fieldset class="field-wide"><legend>Nächster Schritt <span class="form-help">(optional)</span></legend>' +
                  '<p class="field-description">Aktion und Datum gehören zusammen. Ohne beide Angaben wird keine Wiedervorlage angelegt.</p>' +
                  '<div class="form-grid">' +
                    '<div class="field"><label for="activity-next-action">Nächste Aktion</label>' +
                      '<input id="activity-next-action" name="nextAction" maxlength="300" placeholder="Angebot nachfassen"></div>' +
                    '<div class="field"><label for="activity-due-on">Fällig am</label>' +
                      '<input id="activity-due-on" name="dueOn" type="date"></div>' +
                  '</div></fieldset>' +
                '<div class="form-actions field-wide">' +
                  '<button class="button" data-testid="activity-submit" type="submit" disabled>Aktivität speichern</button>' +
                '</div>' +
                '<p id="activity-status" class="form-status field-wide" role="status" aria-live="polite"></p>' +
              '</form>' +
            '</section>' +
            '<section class="panel" aria-labelledby="reminder-heading">' +
              '<div class="result-heading"><div>' +
                '<h2 id="reminder-heading">Heute im Blick</h2>' +
                '<p class="form-help">Überfälliges und heute Fälliges steht immer zuerst.</p>' +
              '</div></div>' +
              '<div id="activity-board" aria-live="polite">' +
                '<div class="empty-state">Wiedervorlagen und Verlauf werden geladen …</div>' +
              '</div>' +
            '</section>' +
          '</div>';
      }

      function setupSponsorForm(identity) {
        const form = document.querySelector("#sponsor-form");
        if (!form) return;
        const status = document.querySelector("#sponsor-status");
        const result = document.querySelector("#sponsor-result");
        const previewButton = form.querySelector('[data-testid="sponsor-preview"]');
        const companyInput = form.elements.companyName;
        const givenInput = form.elements.givenName;
        const familyInput = form.elements.familyName;
        let mode = "company";
        let currentMatch = null;
        let currentDraft = null;
        let currentCommandId = null;
        let selectedId = null;

        const setMode = (nextMode) => {
          mode = nextMode;
          form.querySelectorAll("[data-sponsor-mode]").forEach((button) => {
            button.setAttribute(
              "aria-pressed",
              String(button.dataset.sponsorMode === mode),
            );
          });
          form.querySelectorAll("[data-company-field]").forEach((field) => {
            field.hidden = mode !== "company";
          });
          form.querySelectorAll("[data-person-field]").forEach((field) => {
            field.hidden = mode !== "person";
          });
          companyInput.required = mode === "company";
          givenInput.required = mode === "person";
          familyInput.required = mode === "person";
          currentMatch = null;
          currentCommandId = null;
          result.className = "result-empty";
          result.innerHTML = '<div><strong id="sponsor-result-heading">Bereit zur Prüfung</strong>' +
            '<span>LeonAid gleicht nur den führenden Namen ab und zeigt weitere Angaben getrennt.</span></div>';
        };

        form.querySelectorAll("[data-sponsor-mode]").forEach((button) => {
          button.addEventListener("click", () => setMode(button.dataset.sponsorMode));
        });
        setMode("company");

        const draft = () => {
          const values = new FormData(form);
          const optional = (name) => values.get(name)?.toString().trim() || null;
          return {
            companyName: mode === "company" ? optional("companyName") : null,
            givenName: mode === "person" ? optional("givenName") : null,
            familyName: mode === "person" ? optional("familyName") : null,
            email: optional("email"),
            streetLine1: mode === "company" ? optional("streetLine1") : null,
            postalCode: mode === "company" ? optional("postalCode") : null,
            city: mode === "company" ? optional("city") : null,
          };
        };

        const candidateMarkup = (candidate, index, selectable) => {
          const names = candidate.assignedAcquirers.map((item) => item.displayName);
          const meta = [
            candidate.postalCode,
            candidate.city,
            candidate.email,
          ].filter(Boolean);
          const selection = selectable
            ? '<input type="radio" name="matchCandidate" value="' +
              escapeHtml(candidate.twentyId) + '" aria-label="' +
              escapeHtml(candidate.displayName) + ' auswählen">'
            : '<span aria-hidden="true">◆</span>';
          return '<label class="candidate" data-candidate-id="' +
            escapeHtml(candidate.twentyId) + '" data-selected="' +
            String(!selectable && index === 0) + '">' +
              selection + '<span><strong>' + escapeHtml(candidate.displayName) + '</strong>' +
              (meta.length
                ? '<span class="candidate-meta">' +
                  meta.map((item) => '<span>' + escapeHtml(item) + '</span>').join("") +
                  '</span>'
                : '<span class="candidate-meta"><span>Keine weiteren CRM-Angaben</span></span>') +
              (names.length
                ? '<span class="assignment-warning"><strong>Bereits zugeordnet</strong> ' +
                  escapeHtml(names.join(", ")) + ' bearbeitet diesen Sponsor bereits.</span>'
                : '') +
              '</span></label>';
        };

        const selectedCandidate = () =>
          currentMatch?.candidates.find((candidate) => candidate.twentyId === selectedId);

        const updateResolveButton = () => {
          const button = result.querySelector('[data-testid="sponsor-resolve"]');
          if (!button || currentMatch.status === "no_match") return;
          const candidate = selectedCandidate();
          button.disabled = !candidate;
          const hasOtherAssignees = candidate?.assignedAcquirers.some(
            (item) => item.userId !== identity.userId,
          );
          button.textContent = hasOtherAssignees
            ? "Trotzdem ebenfalls zuordnen"
            : "Diesen Sponsor mir zuordnen";
        };

        const renderMatch = (match) => {
          currentMatch = match;
          currentCommandId = crypto.randomUUID();
          selectedId =
            match.status === "single_match" ? match.candidates[0].twentyId : null;
          const selectable = match.status === "ambiguous_match";
          const heading =
            match.status === "no_match"
              ? "Noch nicht im CRM"
              : match.status === "single_match"
                ? "Ein eindeutiger Treffer"
                : "Mehrere mögliche Treffer";
          const badge =
            match.status === "no_match"
              ? "Neu"
              : match.status === "single_match"
                ? "1 Treffer"
                : match.candidates.length + " Treffer";
          const candidates = match.candidates.length
            ? '<div class="candidate-list">' +
              match.candidates.map((item, index) =>
                candidateMarkup(item, index, selectable)
              ).join("") + '</div>'
            : '<div class="success-card"><strong>Kein gleichnamiger Sponsor gefunden</strong>' +
              'Die eingegebenen Daten können als neuer CRM-Datensatz angelegt werden.</div>';
          result.className = "";
          result.innerHTML =
            '<div class="result-heading"><div><h2 id="sponsor-result-heading">' +
              heading + '</h2><p class="form-help">Matchschlüssel: ' +
              escapeHtml(match.normalizedKey) + '</p></div>' +
              '<span class="match-badge">' + escapeHtml(badge) + '</span></div>' +
            candidates +
            (match.status !== "no_match"
              ? '<p class="preserve-note">PLZ, Ort und E-Mail helfen dir bei der Auswahl. Sie ändern einen vorhandenen CRM-Datensatz nicht automatisch.</p>'
              : '') +
            '<div class="form-actions" style="margin-top: 1rem">' +
              '<button class="button" data-testid="sponsor-resolve" type="button">' +
                (match.status === "no_match"
                  ? "Neu anlegen und mir zuordnen"
                  : "Diesen Sponsor mir zuordnen") +
              '</button>' +
              '<button class="button-secondary" data-testid="sponsor-cancel" type="button">Abbrechen</button>' +
            '</div>';
          result.querySelectorAll('[name="matchCandidate"]').forEach((input) => {
            input.addEventListener("change", () => {
              selectedId = input.value;
              result.querySelectorAll("[data-candidate-id]").forEach((candidate) => {
                candidate.dataset.selected =
                  String(candidate.dataset.candidateId === selectedId);
              });
              updateResolveButton();
            });
          });
          result.querySelector('[data-testid="sponsor-cancel"]').addEventListener(
            "click",
            () => {
              currentMatch = null;
              currentCommandId = null;
              result.className = "result-empty";
              result.innerHTML = '<div><strong id="sponsor-result-heading">Prüfung abgebrochen</strong>' +
                '<span>Du kannst die Eingaben anpassen und erneut prüfen.</span></div>';
            },
          );
          result.querySelector('[data-testid="sponsor-resolve"]').addEventListener(
            "click",
            resolve,
          );
          updateResolveButton();
        };

        const resolve = async () => {
          if (!currentMatch || !currentDraft || !currentCommandId) return;
          const button = result.querySelector('[data-testid="sponsor-resolve"]');
          const candidate = selectedCandidate();
          const hasOtherAssignees = candidate?.assignedAcquirers.some(
            (item) => item.userId !== identity.userId,
          ) ?? false;
          button.disabled = true;
          status.dataset.state = "";
          status.textContent = "Zuordnung wird sicher gespeichert …";
          try {
            const response = await fetch(
              "/api/v1/actions/" + encodeURIComponent(form.elements.actionId.value) +
                "/acquisition/sponsor-match/resolve",
              {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify({
                  commandId: currentCommandId,
                  sponsor: currentDraft,
                  expectedStatus: currentMatch.status,
                  selectedTwentyId: selectedId,
                  confirmExistingAssignments: hasOtherAssignees,
                }),
              },
            );
            if (!response.ok) {
              const failure = await response.json().catch(() => ({}));
              if (failure.error?.code === "sponsor_match_changed") {
                throw new Error("changed");
              }
              throw new Error("resolve");
            }
            const resolution = await response.json();
            const sharedAssignees = [
              ...resolution.priorAssignees,
              { userId: identity.userId, displayName: identity.displayName },
            ]
              .filter(
                (item, index, values) =>
                  values.findIndex((candidate) => candidate.userId === item.userId) ===
                  index,
              )
              .sort((left, right) =>
                left.displayName.localeCompare(right.displayName, "de"),
              );
            const sharedMarkup =
              sharedAssignees.length > 1
                ? '<span class="assignment-warning" data-testid="shared-assignees">' +
                  '<strong>Gemeinsam betreut</strong> ' +
                  escapeHtml(
                    sharedAssignees.map((item) => item.displayName).join(", "),
                  ) +
                  "</span>"
                : "";
            status.dataset.state = "success";
            status.textContent = resolution.displayName + " ist jetzt dir zugeordnet.";
            result.innerHTML = '<div class="success-card" data-testid="sponsor-success">' +
              '<strong>Zuordnung gespeichert</strong>' +
              escapeHtml(resolution.displayName) +
              (resolution.outcome === "created"
                ? " wurde neu im CRM angelegt."
                : " wurde aus dem CRM übernommen.") +
              sharedMarkup +
              '</div><div class="form-actions" style="margin-top: 1rem">' +
              '<button class="button-secondary" data-testid="sponsor-next" type="button">Weiteren Sponsor erfassen</button></div>';
            result.querySelector('[data-testid="sponsor-next"]').addEventListener(
              "click",
              () => {
                form.reset();
                setMode("company");
                status.textContent = "";
                companyInput.focus();
              },
            );
          } catch (error) {
            status.dataset.state = "error";
            status.textContent = error.message === "changed"
              ? "Der CRM-Bestand hat sich geändert. Bitte prüfe erneut."
              : "Die Zuordnung konnte nicht gespeichert werden. Versuche es erneut.";
            button.disabled = false;
          }
        };

        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          previewButton.disabled = true;
          status.dataset.state = "";
          status.textContent = "CRM-Bestand wird geprüft …";
          currentDraft = draft();
          try {
            const response = await fetch(
              "/api/v1/actions/" + encodeURIComponent(form.elements.actionId.value) +
                "/acquisition/sponsor-match",
              {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify(currentDraft),
              },
            );
            if (!response.ok) throw new Error("preview");
            renderMatch(await response.json());
            status.textContent = "";
          } catch {
            status.dataset.state = "error";
            status.textContent = "Der CRM-Bestand konnte nicht geprüft werden. Versuche es erneut.";
          } finally {
            previewButton.disabled = false;
          }
        });
      }

      function setupActivityBoard() {
        const form = document.querySelector("#activity-form");
        if (!form) return;
        const actionSelect = form.elements.actionId;
        const partySelect = form.elements.party;
        const note = form.elements.note;
        const nextAction = form.elements.nextAction;
        const dueOn = form.elements.dueOn;
        const submit = form.querySelector('[data-testid="activity-submit"]');
        const status = document.querySelector("#activity-status");
        const boardRoot = document.querySelector("#activity-board");
        const noteCount = document.querySelector("#activity-note-count");
        const workItems = new Map();
        let loading = false;

        const channelLabels = {
          phone: "Telefon",
          email: "E-Mail",
          in_person: "Persönlich",
        };
        const outcomeLabels = {
          reached: "Erreicht",
          no_answer: "Nicht erreicht",
          interested: "Interesse",
          follow_up: "Später nachfassen",
          committed: "Zusage",
          declined: "Absage",
        };
        const localDate = (value, options = {}) =>
          new Intl.DateTimeFormat("de-DE", {
            timeZone: "Europe/Berlin",
            day: "2-digit",
            month: "short",
            year: "numeric",
            ...options,
          }).format(new Date(value));
        const localDateTime = (value) =>
          new Intl.DateTimeFormat("de-DE", {
            timeZone: "Europe/Berlin",
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          }).format(new Date(value));
        dueOn.min = new Intl.DateTimeFormat("sv-SE", {
          timeZone: "Europe/Berlin",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
        }).format(new Date());

        const syncReminderPair = () => {
          const hasAction = nextAction.value.trim().length > 0;
          const hasDate = dueOn.value.length > 0;
          nextAction.required = hasDate;
          dueOn.required = hasAction;
        };
        nextAction.addEventListener("input", syncReminderPair);
        dueOn.addEventListener("input", syncReminderPair);
        note.addEventListener("input", () => {
          noteCount.textContent =
            new Intl.NumberFormat("de-DE").format(note.value.length) + " / 2.000";
        });

        const reminderLabel = (item) => {
          if (item.urgency === "overdue") return "Überfällig";
          if (item.urgency === "today") return "Heute";
          return item.dueAt ? localDate(item.dueAt, { year: undefined }) : "";
        };

        const renderBoard = (payload) => {
          const reminders = payload.workItems.filter(
            (item) => item.nextAction && item.dueAt,
          );
          const counts = {
            overdue: reminders.filter((item) => item.urgency === "overdue").length,
            today: reminders.filter((item) => item.urgency === "today").length,
            upcoming: reminders.filter((item) => item.urgency === "upcoming").length,
          };
          const reminderMarkup = reminders.length
            ? '<div class="reminder-list" data-testid="reminder-list">' +
              reminders.map((item) =>
                '<button class="reminder-card" type="button" data-select-assignment="' +
                  escapeHtml(item.assignmentId) + '">' +
                  '<span class="urgency-dot" data-urgency="' +
                    escapeHtml(item.urgency) + '" aria-hidden="true"></span>' +
                  '<span class="reminder-copy"><strong>' +
                    escapeHtml(item.partyDisplayName) + '</strong><span>' +
                    escapeHtml(item.nextAction) + '</span></span>' +
                  '<span class="reminder-date">' +
                    escapeHtml(reminderLabel(item)) + '</span>' +
                '</button>'
              ).join("") + '</div>'
            : '<div class="empty-state">Keine Wiedervorlage fällig. Du kannst beim Erfassen einer Aktivität direkt den nächsten Schritt planen.</div>';
          const timelineMarkup = payload.activities.length
            ? '<div class="activity-timeline" data-testid="activity-timeline">' +
              payload.activities.map((item) =>
                '<article class="timeline-card" data-testid="activity-entry" data-activity-id="' +
                  escapeHtml(item.id) + '">' +
                  '<strong>' + escapeHtml(item.partyDisplayName) + '</strong>' +
                  '<div class="timeline-meta"><span>' +
                    escapeHtml(outcomeLabels[item.outcome] ?? item.outcome) +
                  '</span><span>' +
                    escapeHtml(channelLabels[item.channel] ?? item.channel) +
                  '</span><span>' + escapeHtml(item.actorDisplayName) +
                  '</span><time datetime="' + escapeHtml(item.occurredAt) + '">' +
                    escapeHtml(localDateTime(item.occurredAt)) + '</time></div>' +
                  (item.note
                    ? '<p class="timeline-note">' + escapeHtml(item.note) + '</p>'
                    : '') +
                  (item.nextAction && item.dueAt
                    ? '<div class="timeline-next"><strong>Nächster Schritt</strong>' +
                      escapeHtml(item.nextAction) + ' · ' +
                      escapeHtml(localDate(item.dueAt)) + '</div>'
                    : '') +
                '</article>'
              ).join("") + '</div>'
            : '<div class="empty-state">Noch keine manuelle Aktivität erfasst.</div>';
          boardRoot.innerHTML =
            '<div class="reminder-summary" aria-label="Wiedervorlagen-Übersicht">' +
              '<div class="summary-tile" data-urgency="overdue"><strong data-testid="overdue-count">' +
                counts.overdue + '</strong><span>Überfällig</span></div>' +
              '<div class="summary-tile" data-urgency="today"><strong data-testid="today-count">' +
                counts.today + '</strong><span>Heute</span></div>' +
              '<div class="summary-tile"><strong>' + counts.upcoming +
                '</strong><span>Demnächst</span></div>' +
            '</div>' +
            reminderMarkup +
            '<div class="timeline-section"><div class="result-heading"><div>' +
              '<h2>Letzte Aktivitäten</h2>' +
              '<p class="form-help">Neueste Einträge zuerst; bestehende Einträge werden nicht überschrieben.</p>' +
            '</div></div>' + timelineMarkup + '</div>';
          boardRoot.querySelectorAll("[data-select-assignment]").forEach((button) => {
            button.addEventListener("click", () => {
              partySelect.value = button.dataset.selectAssignment;
              form.querySelector("#activity-channel").focus();
              form.scrollIntoView({ behavior: "smooth", block: "start" });
            });
          });
        };

        const loadBoard = async () => {
          if (!actionSelect.value) return;
          loading = true;
          submit.disabled = true;
          boardRoot.innerHTML =
            '<div class="empty-state">Wiedervorlagen und Verlauf werden geladen …</div>';
          try {
            const response = await fetch(
              "/api/v1/actions/" + encodeURIComponent(actionSelect.value) +
                "/acquisition/activity-board?limit=50",
              {
                credentials: "include",
                headers: { Accept: "application/json" },
              },
            );
            if (!response.ok) throw new Error("board");
            const payload = await response.json();
            const previousSelection = partySelect.value;
            workItems.clear();
            partySelect.replaceChildren();
            for (const item of payload.workItems) {
              workItems.set(item.assignmentId, item);
              const option = document.createElement("option");
              option.value = item.assignmentId;
              option.textContent = item.partyDisplayName +
                (item.city ? " · " + item.city : "");
              partySelect.append(option);
            }
            if (workItems.has(previousSelection)) {
              partySelect.value = previousSelection;
            }
            partySelect.disabled = payload.workItems.length === 0;
            submit.disabled = payload.workItems.length === 0;
            if (payload.workItems.length === 0) {
              const option = document.createElement("option");
              option.value = "";
              option.textContent = "Noch kein Sponsor zugeordnet";
              partySelect.append(option);
            }
            renderBoard(payload);
          } catch {
            partySelect.disabled = true;
            submit.disabled = true;
            boardRoot.innerHTML =
              '<div class="empty-state">Wiedervorlagen konnten nicht geladen werden. Bitte versuche es erneut.</div>';
          } finally {
            loading = false;
          }
        };

        actionSelect.addEventListener("change", loadBoard);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          if (loading) return;
          const selected = workItems.get(partySelect.value);
          if (!selected) return;
          const nextActionValue = nextAction.value.trim() || null;
          const dueOnValue = dueOn.value || null;
          if ((nextActionValue === null) !== (dueOnValue === null)) {
            status.dataset.state = "error";
            status.textContent =
              "Ergänze für die Wiedervorlage sowohl nächste Aktion als auch Datum.";
            syncReminderPair();
            return;
          }
          submit.disabled = true;
          status.dataset.state = "";
          status.textContent = "Aktivität und Wiedervorlage werden gespeichert …";
          const values = new FormData(form);
          try {
            const response = await fetch(
              "/api/v1/actions/" + encodeURIComponent(actionSelect.value) +
                "/acquisition/activities",
              {
                method: "POST",
                credentials: "include",
                headers: {
                  "Content-Type": "application/json",
                  Accept: "application/json",
                },
                body: JSON.stringify({
                  partyKind: selected.partyKind,
                  partyId: selected.partyId,
                  revision: selected.revision,
                  channel: values.get("channel"),
                  outcome: values.get("outcome"),
                  note: note.value.trim() || null,
                  nextAction: nextActionValue,
                  dueOn: dueOnValue,
                }),
              },
            );
            if (!response.ok) {
              const failure = await response.json().catch(() => ({}));
              if (failure.error?.code === "assignment_revision_conflict") {
                throw new Error("changed");
              }
              throw new Error("record");
            }
            const recorded = await response.json();
            status.dataset.state = "success";
            status.textContent = "Aktivität für " +
              recorded.activity.partyDisplayName + " wurde gespeichert.";
            note.value = "";
            nextAction.value = "";
            dueOn.value = "";
            note.dispatchEvent(new Event("input"));
            syncReminderPair();
            await loadBoard();
          } catch (error) {
            status.dataset.state = "error";
            status.textContent = error.message === "changed"
              ? "Die Zuordnung wurde gerade geändert. Die Ansicht wurde aktualisiert; bitte prüfe den Eintrag noch einmal."
              : "Die Aktivität konnte nicht gespeichert werden. Versuche es erneut.";
            await loadBoard();
          } finally {
            submit.disabled = partySelect.disabled;
          }
        });
        loadBoard();
      }

      function beneficiaryRow(index) {
        const row = document.createElement("div");
        row.className = "beneficiary-row";
        row.dataset.beneficiaryIndex = String(index);
        row.innerHTML = '<div class="field"><label>Name der Organisation' +
          '<input data-testid="beneficiary-name-' + index + '" name="beneficiaryName" maxlength="200" required></label></div>' +
          '<div class="field"><label>Öffentliche Beschreibung' +
          '<textarea data-testid="beneficiary-description-' + index + '" name="beneficiaryDescription" maxlength="2000" required></textarea></label></div>';
        return row;
      }

      function setupActionCreationForm() {
        const form = document.querySelector("#action-form");
        if (!form) return;
        const list = document.querySelector("#beneficiary-list");
        const add = form.querySelector('[data-testid="add-beneficiary"]');
        const submit = form.querySelector('[data-testid="action-submit"]');
        const status = document.querySelector("#action-status");
        let beneficiaryCount = 0;
        const addBeneficiary = () => {
          list.append(beneficiaryRow(beneficiaryCount));
          beneficiaryCount += 1;
        };
        addBeneficiary();
        add.addEventListener("click", addBeneficiary);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          submit.disabled = true;
          status.dataset.state = "";
          status.textContent = "Charity-Aktion wird sicher angelegt …";
          const values = new FormData(form);
          const beneficiaries = [...list.querySelectorAll(".beneficiary-row")].map((row) => ({
            organizationName: row.querySelector('[name="beneficiaryName"]').value,
            publicDescription: row.querySelector('[name="beneficiaryDescription"]').value,
          }));
          const currency = values.get("currency")?.toString().trim();
          try {
            const response = await fetch("/api/v1/actions", {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify({
                carrierName: values.get("carrierName"),
                name: values.get("name"),
                purpose: values.get("purpose"),
                startsOn: values.get("startsOn"),
                endsOn: values.get("endsOn"),
                archiveSlug: values.get("archiveSlug"),
                capabilities: values.getAll("capability"),
                beneficiaries,
                goal: {
                  goalValue: values.get("goalValue"),
                  actualValue: values.get("actualValue"),
                  unit: values.get("unit"),
                  currency: currency || null,
                },
              }),
            });
            if (!response.ok) {
              const failure = await response.json().catch(() => ({}));
              if (failure.error?.code === "fresh_login_required") {
                const returnTo = encodeURIComponent(window.location.pathname);
                window.location.assign("/fresh-login?returnTo=" + returnTo);
                return;
              }
              throw new Error(failure.error?.code ?? "create");
            }
            const action = await response.json();
            status.dataset.state = "success";
            status.dataset.actionId = action.id;
            status.textContent = action.name + " wurde als Entwurf angelegt.";
            form.reset();
          } catch {
            status.dataset.state = "error";
            status.textContent = "Die Aktion konnte nicht angelegt werden. Prüfe Zeitraum, Slug, Ziel und Begünstigte.";
          } finally {
            submit.disabled = false;
          }
        });
      }

      function appendOptions(select, options, valueKey, labelKey) {
        select.replaceChildren();
        for (const option of options) {
          const element = document.createElement("option");
          element.value = option[valueKey];
          element.textContent = option[labelKey];
          select.append(element);
        }
      }

      async function setupInvitationForm() {
        const form = document.querySelector("#invitation-form");
        if (!form) return;
        const action = form.elements.actionId;
        const role = form.elements.role;
        const submit = form.querySelector('[data-testid="invite-submit"]');
        const status = document.querySelector("#invitation-status");
        try {
          const response = await fetch("/api/v1/invitations/options", {
            credentials: "include",
            headers: { Accept: "application/json" },
          });
          if (!response.ok) throw new Error("options");
          const options = await response.json();
          appendOptions(action, options.actions, "id", "name");
          appendOptions(role, options.roles, "value", "label");
          action.disabled = options.actions.length === 0;
          role.disabled = options.roles.length === 0;
          submit.disabled = options.actions.length === 0;
          if (options.actions.length === 0) {
            status.dataset.state = "error";
            status.textContent = "Du verwaltest derzeit keine einladbare Charity-Aktion.";
          }
        } catch {
          status.dataset.state = "error";
          status.textContent = "Einladungsoptionen konnten nicht geladen werden.";
        }
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          submit.disabled = true;
          status.dataset.state = "";
          status.textContent = "Einladung wird sicher versendet …";
          const values = new FormData(form);
          try {
            const response = await fetch("/api/v1/invitations", {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify({
                actionId: values.get("actionId"),
                displayName: values.get("displayName"),
                email: values.get("email"),
                role: values.get("role"),
              }),
            });
            if (!response.ok) {
              const failure = await response.json().catch(() => ({}));
              if (failure.error?.code === "fresh_login_required") {
                const returnTo = encodeURIComponent(window.location.pathname);
                window.location.assign("/fresh-login?returnTo=" + returnTo);
                return;
              }
              throw new Error("dispatch");
            }
            status.dataset.state = "success";
            status.textContent = "Einladung eingeplant. Magic Link und Code werden per E-Mail versendet.";
            form.elements.displayName.value = "";
            form.elements.email.value = "";
          } catch {
            status.dataset.state = "error";
            status.textContent = "Die Einladung konnte nicht versendet werden. Prüfe deine Berechtigung und versuche es erneut.";
          } finally {
            submit.disabled = action.disabled;
          }
        });
      }

      function setupLogout() {
        const button = document.querySelector('[data-testid="logout"]');
        if (!button) return;
        button.addEventListener("click", async () => {
          button.disabled = true;
          await fetch("/api/v1/auth/logout", {
            method: "POST",
            credentials: "include",
            headers: { Accept: "application/json" },
          }).catch(() => undefined);
          window.location.assign("/login");
        });
      }

      function renderIdentity(identity) {
        const surface = configuration.appKind === "pwa" ? "pwa" : "web";
        const navigation = identity.navigation.filter(
          (item) => item.surface === surface,
        );
        const memberships = identity.actionMemberships;
        const currentAction = memberships[0]?.actionName ?? "Keine aktive Aktion";
        root.className = "";
        root.innerHTML = '<div class="shell">' +
          '<aside class="sidebar">' +
            '<div class="brand"><span class="brand-mark">L</span><span>LeonAid</span></div>' +
            '<p class="nav-label">Arbeitsbereich</p>' +
            navMarkup(navigation, "desktop-nav") +
            '<div class="sidebar-context"><small>Aktuelle Aktion</small>' +
              '<strong data-testid="current-action">' + escapeHtml(currentAction) + '</strong></div>' +
          '</aside>' +
          '<main>' +
            '<header class="topbar">' +
              '<div class="topbar-copy"><small>Angemeldet als</small>' +
                '<strong data-testid="display-name">' + escapeHtml(identity.displayName) + '</strong></div>' +
              '<div><div class="roles" data-testid="roles">' +
                  identity.roleLabels.map((label) =>
                    '<span class="role">' + escapeHtml(label) + '</span>'
                  ).join("") +
                '</div><button class="button-secondary" data-testid="logout" type="button">Abmelden</button></div>' +
            '</header>' +
            '<div class="content">' +
              (surface === "web" && window.location.pathname.startsWith("/admin/actions/new")
                ? actionCreationMarkup()
                : surface === "web" && window.location.pathname.startsWith("/admin/members")
                  ? invitationMarkup()
                  : surface === "pwa" && window.location.pathname.startsWith("/app/sponsors")
                    ? sponsorMarkup(identity)
                  : surface === "pwa" && window.location.pathname.startsWith("/app/activities")
                    ? activityMarkup(identity)
                  : dashboardMarkup(identity, surface)) +
            '</div>' +
          '</main>' +
          navMarkup(navigation, "mobile-nav") +
        '</div>';
        setupInvitationForm();
        setupActionCreationForm();
        setupSponsorForm(identity);
        setupActivityBoard();
        setupLogout();
      }

      function renderError(status) {
        const signedOut = status === 401;
        root.className = "";
        root.innerHTML = '<main class="notice" role="alert">' +
          '<p class="eyebrow">' + (signedOut ? "Sitzung beendet" : "Nicht verfügbar") + '</p>' +
          '<h1>' + (signedOut ? "Bitte erneut anmelden" : "Arbeitsbereich nicht erreichbar") + '</h1>' +
          '<p>' + (signedOut
            ? "Deine Sitzung ist abgelaufen oder dein Zugang wurde gesperrt. Melde dich erneut an oder wende dich an einen Charity-Admin."
            : "LeonAid konnte deinen Arbeitsbereich gerade nicht laden. Versuche es bitte noch einmal.") +
          '</p>' + (signedOut ? '<a class="button" href="/login">Zur Anmeldung</a>' : '') + '</main>';
      }

      fetch("/api/v1/identity/me", {
        credentials: "include",
        headers: { Accept: "application/json" },
      }).then(async (response) => {
        if (!response.ok) {
          renderError(response.status);
          return;
        }
        renderIdentity(await response.json());
      }).catch(() => renderError(503));
    </script>
  </body>
</html>`;
}

function authenticationPage(kind) {
  const fresh = kind === "fresh";
  const title = fresh ? "Anmeldung bestätigen" : "Bei LeonAid anmelden";
  const introduction = fresh
    ? "Bestätige deine Anmeldung erneut, bevor du eine sensible Änderung ausführst."
    : "Fordere einen einmaligen Magic Link oder sechsstelligen Code für deine Login-E-Mail an.";
  const requestLabel = fresh
    ? "Code per E-Mail senden"
    : "Login-Code anfordern";
  const requestEndpoint = fresh ? "/api/v1/auth/fresh" : "/api/v1/auth/login";
  const completeEndpoint = fresh
    ? "/api/v1/auth/fresh/complete"
    : "/api/v1/auth/login/complete";
  return `<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="referrer" content="no-referrer">
    <meta name="color-scheme" content="light">
    <title>${title} · LeonAid</title>
    <style>
      :root { color: #13233f; background: #f4f6fa; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      * { box-sizing: border-box; }
      body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 1rem; }
      main { width: min(100%, 31rem); padding: clamp(1.4rem, 5vw, 2.2rem); border: 1px solid #dfe5ee; border-radius: 1.1rem; background: #fff; box-shadow: 0 22px 55px rgba(19,35,63,.1); }
      .mark { display: grid; width: 2.6rem; height: 2.6rem; place-items: center; border-radius: .8rem; color: #13233f; background: #e6bd4f; font-weight: 850; }
      .eyebrow { margin-top: 1.5rem; color: #936f12; font-size: .75rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
      h1 { margin: .35rem 0 .6rem; font-size: clamp(1.75rem, 7vw, 2.5rem); letter-spacing: -.04em; }
      .lead, .status, .help { color: #617089; line-height: 1.6; }
      form { display: grid; gap: .9rem; margin-top: 1.4rem; }
      .field { display: grid; gap: .4rem; }
      label { font-size: .82rem; font-weight: 720; }
      input { min-height: 2.9rem; padding: .68rem .75rem; border: 1px solid #cbd5e3; border-radius: .68rem; color: #13233f; font: inherit; }
      input:focus { border-color: #8b6b19; outline: 3px solid rgba(230,189,79,.28); }
      button { min-height: 2.9rem; padding: .7rem 1rem; border: 0; border-radius: .68rem; color: #13233f; background: #e6bd4f; font: inherit; font-weight: 780; cursor: pointer; }
      button:disabled { cursor: wait; opacity: .6; }
      .status[data-state="success"] { color: #167044; }
      .status[data-state="error"] { color: #a33a2c; }
      [hidden] { display: none !important; }
    </style>
  </head>
  <body>
    <main>
      <div class="mark" aria-hidden="true">L</div>
      <p class="eyebrow">Sicherer Zugang</p>
      <h1>${title}</h1>
      <p class="lead" id="auth-intro">${introduction}</p>
      <form id="request-login-form">
        ${
          fresh
            ? ""
            : '<div class="field"><label for="login-email">Login-E-Mail</label><input id="login-email" name="email" type="email" autocomplete="email" required></div>'
        }
        <button data-testid="request-login" type="submit">${requestLabel}</button>
        <p class="help">Aus Sicherheitsgründen ist die Antwort immer gleich – auch wenn die Adresse nicht registriert ist.</p>
      </form>
      <form id="complete-login-form" hidden>
        ${
          fresh
            ? ""
            : '<div class="field code-email"><label for="complete-email">Login-E-Mail</label><input id="complete-email" name="email" type="email" autocomplete="email" required></div>'
        }
        <div class="field code-field"><label for="login-code">Sechsstelliger Code</label><input id="login-code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required></div>
        <button data-testid="complete-login" type="submit">${fresh ? "Anmeldung bestätigen" : "Anmelden"}</button>
      </form>
      <p id="auth-status" class="status" role="status" aria-live="polite"></p>
    </main>
    <script>
      const fresh = ${JSON.stringify(fresh)};
      const requestEndpoint = ${JSON.stringify(requestEndpoint)};
      const completeEndpoint = ${JSON.stringify(completeEndpoint)};
      const requestForm = document.querySelector("#request-login-form");
      const completeForm = document.querySelector("#complete-login-form");
      const status = document.querySelector("#auth-status");
      const parameters = new URLSearchParams(window.location.search);
      const token = parameters.get("token");
      const requestedReturnTo = parameters.get("returnTo") ?? (fresh ? "/admin/" : "/app/");
      const returnTo = requestedReturnTo.startsWith("/") && !requestedReturnTo.startsWith("//")
        ? requestedReturnTo
        : (fresh ? "/admin/" : "/app/");

      function showCode(email) {
        requestForm.hidden = true;
        completeForm.hidden = false;
        if (!fresh && email) completeForm.elements.email.value = email;
        completeForm.elements.code.focus();
      }

      if (token) {
        requestForm.hidden = true;
        completeForm.hidden = false;
        document.querySelectorAll(".code-field, .code-email").forEach((field) => field.hidden = true);
        if (completeForm.elements.code) completeForm.elements.code.required = false;
        if (completeForm.elements.email) completeForm.elements.email.required = false;
        document.querySelector("#auth-intro").textContent = "Der Magic Link ist bereit. Bestätige die einmalige Anmeldung.";
        window.history.replaceState({}, "", window.location.pathname + "?returnTo=" + encodeURIComponent(returnTo));
      }

      requestForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = requestForm.querySelector("button");
        button.disabled = true;
        status.dataset.state = "";
        status.textContent = "Sicherer Zugang wird vorbereitet …";
        const email = fresh ? null : requestForm.elements.email.value;
        try {
          const response = await fetch(requestEndpoint, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: fresh ? undefined : JSON.stringify({ email }),
          });
          if (!response.ok) throw new Error("request");
          status.dataset.state = "success";
          status.textContent = "Wenn der Zugang berechtigt ist, wurde eine E-Mail versendet. Gib den Code hier ein.";
          showCode(email);
        } catch {
          status.dataset.state = "error";
          status.textContent = fresh
            ? "Deine Sitzung ist nicht mehr gültig. Bitte melde dich vollständig neu an."
            : "Der Login konnte gerade nicht vorbereitet werden. Versuche es erneut.";
          button.disabled = false;
        }
      });

      completeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = completeForm.querySelector("button");
        button.disabled = true;
        status.dataset.state = "";
        status.textContent = "Anmeldung wird sicher bestätigt …";
        const body = token
          ? { magicToken: token }
          : fresh
            ? { code: completeForm.elements.code.value }
            : {
                email: completeForm.elements.email.value,
                code: completeForm.elements.code.value,
              };
        try {
          const response = await fetch(completeEndpoint, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify(body),
          });
          if (!response.ok) throw new Error("complete");
          status.dataset.state = "success";
          status.textContent = fresh ? "Bestätigt. Du kannst fortfahren." : "Erfolgreich angemeldet.";
          window.location.replace(returnTo);
        } catch {
          status.dataset.state = "error";
          status.textContent = "Link oder Code ist ungültig oder abgelaufen. Fordere einen neuen Zugang an.";
          button.disabled = false;
        }
      });
    </script>
  </body>
</html>`;
}

function publicPage(requestUrl) {
  if (requestUrl.startsWith("/fresh-login")) {
    return authenticationPage("fresh");
  }
  if (requestUrl.startsWith("/login")) {
    return authenticationPage("login");
  }
  if (!requestUrl.startsWith("/invite")) {
    return `<!doctype html>
<html lang="de">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
    <title>${escapeHtml(appName)}</title></head>
  <body><main><h1>${escapeHtml(appName)}</h1><p>LeonAid ${escapeHtml(appKind)} ist bereit.</p></main></body>
</html>`;
  }
  return `<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="referrer" content="no-referrer">
    <meta name="color-scheme" content="light">
    <title>Einladung annehmen · LeonAid</title>
    <style>
      :root { color: #13233f; background: #f4f6fa; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      * { box-sizing: border-box; }
      body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 1rem; }
      main { width: min(100%, 31rem); padding: clamp(1.4rem, 5vw, 2.2rem); border: 1px solid #dfe5ee; border-radius: 1.1rem; background: #fff; box-shadow: 0 22px 55px rgba(19,35,63,.1); }
      .mark { display: grid; width: 2.6rem; height: 2.6rem; place-items: center; border-radius: .8rem; color: #13233f; background: #e6bd4f; font-weight: 850; }
      .eyebrow { margin-top: 1.5rem; color: #936f12; font-size: .75rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
      h1 { margin: .35rem 0 .6rem; font-size: clamp(1.75rem, 7vw, 2.5rem); letter-spacing: -.04em; }
      .lead, .status { color: #617089; line-height: 1.6; }
      form { display: grid; gap: .9rem; margin-top: 1.4rem; }
      .field { display: grid; gap: .4rem; }
      label { font-size: .82rem; font-weight: 720; }
      input { min-height: 2.9rem; padding: .68rem .75rem; border: 1px solid #cbd5e3; border-radius: .68rem; color: #13233f; font: inherit; }
      input:focus { border-color: #8b6b19; outline: 3px solid rgba(230,189,79,.28); }
      button { min-height: 2.9rem; padding: .7rem 1rem; border: 0; border-radius: .68rem; color: #13233f; background: #e6bd4f; font: inherit; font-weight: 780; cursor: pointer; }
      button:disabled { cursor: wait; opacity: .6; }
      .status[data-state="success"] { color: #167044; }
      .status[data-state="error"] { color: #a33a2c; }
    </style>
  </head>
  <body>
    <main>
      <div class="mark" aria-hidden="true">L</div>
      <p class="eyebrow">Sicherer Zugang</p>
      <h1>Einladung annehmen</h1>
      <p class="lead" id="intro">Bestätige deine Einladung per Magic Link oder mit dem sechsstelligen Code aus deiner E-Mail.</p>
      <form id="accept-form">
        <div class="field code-field"><label for="accept-email">E-Mail</label><input id="accept-email" name="email" type="email" autocomplete="email" required></div>
        <div class="field code-field"><label for="accept-code">Sechsstelliger Code</label><input id="accept-code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required></div>
        <button data-testid="accept-submit" type="submit">Einladung bestätigen</button>
        <p id="accept-status" class="status" role="status" aria-live="polite"></p>
      </form>
    </main>
    <script>
      const form = document.querySelector("#accept-form");
      const status = document.querySelector("#accept-status");
      const submit = form.querySelector("button");
      const token = new URLSearchParams(window.location.search).get("token");
      if (token) {
        document.querySelectorAll(".code-field").forEach((field) => field.hidden = true);
        form.elements.email.required = false;
        form.elements.code.required = false;
        document.querySelector("#intro").textContent = "Der Magic Link ist bereit. Bestätige einmalig deine Mitgliedschaft und Aktionsrolle.";
        window.history.replaceState({}, "", "/invite");
      }
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        status.dataset.state = "";
        status.textContent = "Einladung wird geprüft …";
        const body = token
          ? { magicToken: token }
          : { email: form.elements.email.value, code: form.elements.code.value };
        try {
          const response = await fetch("/api/v1/invitations/accept", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify(body),
          });
          if (!response.ok) throw new Error("invalid");
          const accepted = await response.json();
          status.dataset.state = "success";
          status.textContent = "Einladung für „" + accepted.actionName + "“ angenommen. Dein Zugang ist aktiviert. ";
          const workspaceLink = document.createElement("a");
          workspaceLink.href = "/app/";
          workspaceLink.textContent = "Zum Arbeitsbereich";
          status.append(workspaceLink);
          submit.hidden = true;
          document.querySelectorAll(".field").forEach((field) => field.hidden = true);
        } catch {
          status.dataset.state = "error";
          status.textContent = "Diese Einladung ist ungültig oder nicht mehr gültig. Bitte fordere eine neue Einladung an.";
          submit.disabled = false;
        }
      });
    </script>
  </body>
</html>`;
}

function publicDate(value) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

function publicActionDocument(route) {
  const action = route.action;
  const archived = route.availability === "archive";
  const beneficiaryItems = action.beneficiaries
    .map(
      (beneficiary) =>
        `<li><strong>${escapeHtml(beneficiary.organizationName)}</strong>` +
        `<span>${escapeHtml(beneficiary.publicDescription)}</span></li>`,
    )
    .join("");
  const goalValue = Number(action.goal.goalValue);
  const actualValue = Number(action.goal.actualValue);
  const progress =
    Number.isFinite(goalValue) && goalValue > 0 && Number.isFinite(actualValue)
      ? Math.min(100, Math.max(0, (actualValue / goalValue) * 100))
      : null;
  const goalMarkup =
    progress === null
      ? ""
      : `<section class="goal" aria-labelledby="goal-heading">` +
        `<div><p class="section-kicker">Gemeinsames Ziel</p>` +
        `<h2 id="goal-heading">${escapeHtml(action.goal.goalValue)} ${escapeHtml(action.goal.unit ?? "")}</h2>` +
        `<p>${escapeHtml(action.goal.actualValue)} ${escapeHtml(action.goal.unit ?? "")} sind bereits erreicht.</p></div>` +
        `<div class="progress" role="progressbar" aria-label="Aktionsfortschritt" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress)}">` +
        `<span style="width:${progress.toFixed(2)}%"></span></div></section>`;
  const archiveForm = archived
    ? `<section class="order-card" aria-labelledby="order-heading">` +
      `<p class="section-kicker">Archivansicht</p>` +
      `<h2 id="order-heading">Diese Aktion ist abgeschlossen</h2>` +
      `<p>Die Aktionsdaten bleiben dauerhaft lesbar. Neue Bestellungen oder Zusagen sind über diese Archiv-Adresse nicht möglich.</p>` +
      `<form aria-label="Bestellformular" data-testid="public-order-form">` +
      `<fieldset disabled><label>Firma<input name="companyName" placeholder="Firma"></label>` +
      `<label>Anzahl<input inputmode="numeric" name="quantity" value="1"></label>` +
      `<button data-testid="public-order-submit" type="submit">Bestellung nicht mehr möglich</button></fieldset></form></section>`
    : `<section class="order-card order-card--active" aria-labelledby="order-heading">` +
      `<p class="section-kicker">Aktuelle Aktion</p>` +
      `<h2 id="order-heading">Gemeinsam mehr bewegen</h2>` +
      `<p>Die öffentliche Aktionsseite ist geöffnet. Sobald Bestellungen möglich sind, wird die Bestellmöglichkeit hier freigeschaltet.</p></section>`;
  return `<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <meta name="theme-color" content="#00338d">
    <link rel="canonical" href="${escapeHtml(route.canonicalPath)}">
    <title>${escapeHtml(action.name)} · LeonAid</title>
    <style>
      :root { color: #0d2240; background: #f5f7fb; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      * { box-sizing: border-box; }
      body { margin: 0; min-width: 20rem; background: radial-gradient(circle at 88% 5%, rgba(235,183,0,.2), transparent 26rem), #f5f7fb; }
      header, main, footer { width: min(72rem, calc(100% - 2rem)); margin-inline: auto; }
      header { display: flex; align-items: center; justify-content: space-between; padding-block: 1.1rem; }
      .brand { display: flex; gap: .7rem; align-items: center; color: #0d2240; font-weight: 850; letter-spacing: -.02em; }
      .mark { display: grid; width: 2.35rem; height: 2.35rem; place-items: center; border-radius: .72rem; color: white; background: #00338d; box-shadow: inset 0 -3px 0 rgba(13,34,64,.22); }
      .route-state { padding: .42rem .72rem; border: 1px solid ${archived ? "#d8dce5" : "#a8c3ea"}; border-radius: 999px; color: ${archived ? "#55565a" : "#00338d"}; background: ${archived ? "#fff" : "#edf4ff"}; font-size: .78rem; font-weight: 780; }
      main { padding-block: clamp(2.2rem, 8vw, 6rem); }
      .hero { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(18rem, .7fr); gap: clamp(2rem, 6vw, 6rem); align-items: end; }
      .eyebrow, .section-kicker { margin: 0 0 .65rem; color: #00338d; font-size: .76rem; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
      h1 { max-width: 13ch; margin: 0; font-size: clamp(2.5rem, 8vw, 5.7rem); line-height: .96; letter-spacing: -.065em; text-wrap: balance; }
      .lead { max-width: 42rem; margin: 1.35rem 0 0; color: #44546c; font-size: clamp(1.05rem, 2vw, 1.28rem); line-height: 1.65; }
      .facts { display: grid; gap: .8rem; margin: 0; padding: 1.15rem; border: 1px solid #dce3ed; border-radius: 1.25rem; background: rgba(255,255,255,.82); box-shadow: 0 18px 55px rgba(13,34,64,.08); }
      .facts div { display: grid; gap: .15rem; padding: .7rem .75rem; border-radius: .75rem; background: #f5f7fb; }
      dt { color: #69778b; font-size: .76rem; font-weight: 750; text-transform: uppercase; letter-spacing: .06em; }
      dd { margin: 0; font-weight: 720; line-height: 1.45; }
      .content-grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(18rem, .75fr); gap: 1.25rem; margin-top: clamp(3rem, 8vw, 6rem); }
      .beneficiaries, .order-card, .goal { padding: clamp(1.35rem, 3vw, 2rem); border: 1px solid #dce3ed; border-radius: 1.35rem; background: white; box-shadow: 0 16px 48px rgba(13,34,64,.06); }
      h2 { margin: 0; font-size: clamp(1.4rem, 3vw, 2rem); letter-spacing: -.035em; }
      .beneficiaries ul { display: grid; gap: .8rem; margin: 1.3rem 0 0; padding: 0; list-style: none; }
      .beneficiaries li { display: grid; gap: .3rem; padding: 1rem; border-radius: .85rem; background: #f5f7fb; }
      .beneficiaries li span, .order-card p, .goal p { color: #5b687b; line-height: 1.6; }
      .goal { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(0, 1fr) minmax(15rem, .8fr); gap: 2rem; align-items: center; }
      .progress { height: .7rem; overflow: hidden; border-radius: 999px; background: #e7ecf3; }
      .progress span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #00338d, #407cca); }
      fieldset { display: grid; gap: .8rem; margin: 1.15rem 0 0; padding: 0; border: 0; }
      label { display: grid; gap: .35rem; color: #55565a; font-size: .8rem; font-weight: 720; }
      input, button { min-height: 2.8rem; padding: .65rem .75rem; border-radius: .72rem; font: inherit; }
      input { border: 1px solid #ccd5e2; background: #f3f5f8; }
      button { border: 0; color: white; background: #667085; font-weight: 780; }
      fieldset:disabled { opacity: .72; }
      footer { padding-block: 2rem 3rem; color: #69778b; font-size: .85rem; }
      @media (max-width: 48rem) {
        .hero, .content-grid, .goal { grid-template-columns: 1fr; }
        .goal { grid-column: auto; }
        main { padding-top: 2.5rem; }
      }
    </style>
  </head>
  <body data-public-state="${escapeHtml(route.availability)}">
    <header>
      <div class="brand"><span aria-hidden="true" class="mark">L</span><span>LeonAid</span></div>
      <span class="route-state" data-testid="public-route-state">${archived ? "Dauerhaftes Archiv" : "Aktuell veröffentlicht"}</span>
    </header>
    <main>
      <section class="hero">
        <div>
          <p class="eyebrow">${escapeHtml(action.carrierName)}</p>
          <h1 data-testid="public-action-name">${escapeHtml(action.name)}</h1>
          <p class="lead">${escapeHtml(action.purpose)}</p>
        </div>
        <dl class="facts">
          <div><dt>Aktionszeitraum</dt><dd>${escapeHtml(publicDate(action.startsOn))} – ${escapeHtml(publicDate(action.endsOn))}</dd></div>
          <div><dt>Dauerhafte Adresse</dt><dd data-testid="public-canonical-path">${escapeHtml(route.canonicalPath)}</dd></div>
        </dl>
      </section>
      <div class="content-grid">
        <section class="beneficiaries" aria-labelledby="beneficiary-heading">
          <p class="section-kicker">Wem die Aktion hilft</p>
          <h2 id="beneficiary-heading">Gemeinsam für unsere Begünstigten</h2>
          <ul>${beneficiaryItems}</ul>
        </section>
        ${archiveForm}
        ${goalMarkup}
      </div>
    </main>
    <footer>LeonAid · Engagement transparent und nachvollziehbar</footer>
  </body>
</html>`;
}

function publicStateDocument({ title, message, state, statusCode = 200 }) {
  return {
    statusCode,
    body: `<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <meta name="theme-color" content="#00338d">
    <title>${escapeHtml(title)} · LeonAid</title>
    <style>
      :root { color: #0d2240; background: #f5f7fb; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      * { box-sizing: border-box; }
      body { min-height: 100vh; display: grid; place-items: center; margin: 0; padding: 1rem; background: radial-gradient(circle at 80% 5%, rgba(235,183,0,.22), transparent 24rem), #f5f7fb; }
      main { width: min(100%, 38rem); padding: clamp(1.6rem, 6vw, 3.2rem); border: 1px solid #dce3ed; border-radius: 1.5rem; background: rgba(255,255,255,.9); box-shadow: 0 24px 65px rgba(13,34,64,.1); }
      .mark { display: grid; width: 2.7rem; height: 2.7rem; place-items: center; border-radius: .8rem; color: white; background: #00338d; font-weight: 850; }
      .eyebrow { margin: 1.5rem 0 .55rem; color: #00338d; font-size: .76rem; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
      h1 { margin: 0; font-size: clamp(2rem, 8vw, 3.7rem); line-height: 1; letter-spacing: -.055em; text-wrap: balance; }
      p:last-child { margin: 1.15rem 0 0; color: #5b687b; font-size: 1.05rem; line-height: 1.65; }
    </style>
  </head>
  <body data-public-state="${escapeHtml(state)}">
    <main data-testid="public-${escapeHtml(state)}">
      <div aria-hidden="true" class="mark">L</div>
      <p class="eyebrow">Lions helfen vor Ort</p>
      <h1>${escapeHtml(title)}</h1>
      <p>${escapeHtml(message)}</p>
    </main>
  </body>
</html>`,
  };
}

async function resolvedPublicPage(requestUrl) {
  if (
    requestUrl.startsWith("/fresh-login") ||
    requestUrl.startsWith("/login") ||
    requestUrl.startsWith("/invite")
  ) {
    return { body: publicPage(requestUrl), statusCode: 200 };
  }
  const pathname = new URL(requestUrl, "http://localhost").pathname;
  if (pathname === "/") {
    return publicStateDocument({
      title: "Engagement, das ankommt",
      message:
        "Über die Aktionsadresse deines Lions Clubs gelangst du direkt zur aktuell veröffentlichten Charity-Aktion.",
      state: "home",
    });
  }
  const archiveMatch = pathname.match(
    /^\/archive\/([a-z0-9]+(?:-[a-z0-9]+)*)\/?$/,
  );
  const aliasMatch = pathname.match(/^\/([a-z0-9]+(?:-[a-z0-9]+)*)\/?$/);
  const endpoint = archiveMatch
    ? `/api/v1/public/actions/archive/${encodeURIComponent(archiveMatch[1])}`
    : aliasMatch
      ? `/api/v1/public/actions/alias/${encodeURIComponent(aliasMatch[1])}`
      : null;
  if (!endpoint) {
    return publicStateDocument({
      title: "Seite nicht gefunden",
      message:
        "Prüfe die Aktionsadresse oder verwende den Link, den dein Lions Club veröffentlicht hat.",
      state: "not-found",
      statusCode: 404,
    });
  }
  try {
    const response = await fetch(`${coreApiUrl}${endpoint}`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5_000),
    });
    if (response.status === 404) {
      return publicStateDocument({
        title: "Aktion nicht gefunden",
        message:
          "Diese Archiv-Adresse gehört zu keiner veröffentlichten Charity-Aktion.",
        state: "not-found",
        statusCode: 404,
      });
    }
    if (!response.ok) throw new Error(`Core API answered ${response.status}`);
    const route = await response.json();
    if (route.availability === "inactive") {
      return publicStateDocument({
        title: "Derzeit keine aktive Aktion",
        message:
          "Unter dieser Adresse ist im Moment keine Charity-Aktion veröffentlicht. Schau gern später noch einmal vorbei.",
        state: "inactive",
      });
    }
    if (!route.action) throw new Error("Public action response is incomplete");
    return { body: publicActionDocument(route), statusCode: 200 };
  } catch {
    return publicStateDocument({
      title: "Aktionsseite gerade nicht erreichbar",
      message:
        "Die Verbindung konnte nicht hergestellt werden. Bitte versuche es in wenigen Augenblicken erneut.",
      state: "unavailable",
      statusCode: 503,
    });
  }
}

http
  .createServer(async (request, response) => {
    if (request.url === "/health/live" || request.url === "/health/ready") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ service: appKind, status: "ready" }));
      return;
    }
    const staticFile =
      webFile(request.url ?? "/") ?? pwaFile(request.url ?? "/");
    if (staticFile) {
      const extension = path.extname(staticFile);
      const serviceWorker = path.basename(staticFile) === "sw.js";
      response.writeHead(200, {
        "content-type":
          contentTypes.get(extension) ?? "application/octet-stream",
        "cache-control":
          extension === ".html" || serviceWorker
            ? "no-store"
            : "public, max-age=31536000, immutable",
        ...(serviceWorker ? { "service-worker-allowed": "/app/" } : {}),
      });
      fs.createReadStream(staticFile).pipe(response);
      return;
    }
    const page =
      appKind === "public"
        ? await resolvedPublicPage(request.url ?? "/")
        : { body: applicationPage(), statusCode: 200 };
    response.writeHead(page.statusCode, {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
    });
    response.end(page.body);
  })
  .listen(port, "0.0.0.0");

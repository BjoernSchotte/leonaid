import http from "node:http";

const appName = process.env.APP_NAME ?? "LeonAid";
const appKind = process.env.APP_KIND ?? "service";
const port = Number(process.env.PORT ?? "3000");

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
      .mobile-nav { display: none; }
      @media (max-width: 760px) {
        .shell { display: block; padding-bottom: 5rem; }
        .sidebar { display: none; }
        .topbar { align-items: flex-start; }
        .roles { max-width: 55%; }
        .content { padding-top: 1.5rem; }
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
          items.map((item, index) =>
            '<a class="nav-item" data-nav-key="' + escapeHtml(item.key) +
            '" href="' + escapeHtml(item.href) + '"' +
            (index === 0 ? ' aria-current="page"' : '') + '>' +
            '<span aria-hidden="true">◆</span><span>' +
            escapeHtml(item.label) + '</span></a>'
          ).join("") + '</nav>';
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
              '<div class="roles" data-testid="roles">' +
                identity.roleLabels.map((label) =>
                  '<span class="role">' + escapeHtml(label) + '</span>'
                ).join("") +
              '</div>' +
            '</header>' +
            '<div class="content">' +
              '<p class="eyebrow">' + (surface === "pwa" ? "Akquise" : "Verwaltung") + '</p>' +
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
              '</div>' +
            '</div>' +
          '</main>' +
          navMarkup(navigation, "mobile-nav") +
        '</div>';
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
          '</p></main>';
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

const publicPage = `<!doctype html>
<html lang="de">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
    <title>${escapeHtml(appName)}</title></head>
  <body><main><h1>${escapeHtml(appName)}</h1><p>LeonAid ${escapeHtml(appKind)} ist bereit.</p></main></body>
</html>`;

http
  .createServer((request, response) => {
    if (request.url === "/health/live" || request.url === "/health/ready") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ service: appKind, status: "ready" }));
      return;
    }
    response.writeHead(200, {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
    });
    response.end(appKind === "public" ? publicPage : applicationPage());
  })
  .listen(port, "0.0.0.0");

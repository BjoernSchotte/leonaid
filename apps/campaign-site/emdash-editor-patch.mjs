import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { patchCampaignMediaEditor } from "./emdash-media-editor-patch.mjs";
import { patchRepeaterEditor } from "./emdash-repeater-editor-patch.mjs";

export const upstreamEditorSha256 =
  "b7c64e5f4ba4cb760d1694332d920194a107db6d42258fd5358a1201776ce299";

// The released 0.36 client drops the server's _rev envelope and does not send
// revision preconditions. Backport only token transport into its existing UI.
// Authentication and concurrency enforcement remain server-side. No fetch
// interception, request fabrication or substitute editor is introduced.
export function patchEditorSource(source) {
  assert.equal(
    createHash("sha256").update(source).digest("hex"),
    upstreamEditorSha256,
    "EmDash editor source changed; re-review revision transport patch",
  );
  const replace = (before, after) => {
    assert.equal(source.split(before).length, 2);
    source = source.replace(before, after);
  };
  // A CMS logout must revoke the same Core session used by both surfaces.
  // Never open native EmDash auth routes or pretend a failed logout succeeded.
  replace(
    '\tconst res = await apiFetch("/_emdash/api/auth/logout?redirect=/_emdash/admin/login", {\n\t\tmethod: "POST",\n\t\tcredentials: "same-origin"\n\t});\n\tif (res.redirected) window.location.href = res.url;\n\telse window.location.href = "/_emdash/admin/login";',
    '\ttry {\n\t\tconst res = await apiFetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin", redirect: "error" });\n\t\tif (!res.ok) throw new Error("logout_failed");\n\t\twindow.location.href = "/admin/";\n\t} catch {\n\t\twindow.alert("Sign out failed. Please try again; your session may still be active.");\n\t}',
  );
  // Core owns campaign URLs. Keep the native Live View control, but never use
  // the CMS binding UUID as a public slug. Missing metadata hides the link.
  replace(
    "\tconst liveViewUrl = isLive && item?.slug ? contentUrl(collection, item.slug, urlPattern) : null;",
    '\tconst liveViewUrl = collection === "campaign_pages" ? (isLive && /^\\/campaigns\\/[a-z0-9]+(?:-[a-z0-9]+)*\\/$/.test(item?.leonaidLivePath ?? "") ? item.leonaidLivePath : null) : (isLive && item?.slug ? contentUrl(collection, item.slug, urlPattern) : null);',
  );
  // Firefox can retain the old selection when an unfocused editor receives a
  // click in an empty paragraph. Use the supported ProseMirror click seam;
  // preserve modifier/drag/keyboard behavior and never modify document content.
  replace(
    "\tconst editorProps = React$1.useMemo(() => ({ attributes: {",
    `\tconst editorProps = React$1.useMemo(() => ({
\t\thandleClick(view, _position, event) {
\t\t\tif (!view.editable || view.composing || event.button !== 0 ||
\t\t\t\tevent.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return false;
\t\t\tconst paragraph = event.target?.closest?.("p");
\t\t\tif (!paragraph || paragraph.parentElement !== view.dom || paragraph.textContent !== "") return false;
\t\t\tconst position = view.posAtDOM(paragraph, 0);
\t\t\tconst resolved = view.state.doc.resolve(position);
\t\t\tif (resolved.parent.type.name !== "paragraph" || resolved.parent.content.size !== 0) return false;
\t\t\tview.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, position)));
\t\t\tview.focus();
\t\t\treturn true;
\t\t}, attributes: {`,
  );
  // Preserve a typed campaign handoff in the native router. It is form input,
  // never an authorization grant; Core is checked on navigation and creation.
  replace(
    'const contentNewRoute = createRoute({\n\tgetParentRoute: () => adminLayoutRoute,\n\tpath: "/content/$collection/new",\n\tcomponent: ContentNewPage,\n\tstaticData: { fullBleed: true },\n\tvalidateSearch: (search) => ({ locale: typeof search.locale === "string" ? search.locale : void 0 })\n});',
    'const contentNewRoute = createRoute({\n\tgetParentRoute: () => adminLayoutRoute,\n\tpath: "/content/$collection/new",\n\tcomponent: ContentNewPage,\n\tstaticData: { fullBleed: true },\n\tvalidateSearch: (search) => ({ locale: typeof search.locale === "string" ? search.locale : void 0, campaign: typeof search.campaign === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(search.campaign) ? search.campaign : void 0 })\n});',
  );
  replace(
    'const { locale } = useSearch({ from: "/_admin/content/$collection/new" });',
    'const { locale, campaign } = useSearch({ from: "/_admin/content/$collection/new" });',
  );
  replace(
    "\t\tisNew: true,\n\t\tentryLocale: pickerLocale,",
    '\t\tisNew: true,\n\t\tleonaidActionId: collection === "campaign_pages" ? campaign : void 0,\n\t\tkey: campaign ?? "unbound",\n\t\tentryLocale: pickerLocale,',
  );
  replace(
    "function ContentEditor({ collection, collectionLabel, item, fields, isNew,",
    "function ContentEditor({ leonaidActionId, collection, collectionLabel, item, fields, isNew,",
  );
  replace(
    '\tconst [formData, setFormData] = React$1.useState(item?.data || {});\n\tconst [slug, setSlug] = React$1.useState(item?.slug || "");\n\tconst [slugTouched, setSlugTouched] = React$1.useState(!!item?.slug);',
    '\tconst leonaidInitialAction = isNew && collection === "campaign_pages" ? leonaidActionId : void 0;\n\tconst [formData, setFormData] = React$1.useState(item?.data || (leonaidInitialAction ? { action_id: leonaidInitialAction } : {}));\n\tconst [slug, setSlug] = React$1.useState(item?.slug || leonaidInitialAction || "");\n\tconst [slugTouched, setSlugTouched] = React$1.useState(!!item?.slug || !!leonaidInitialAction);',
  );
  for (const [name, message] of [
    ["fetchContent", "Failed to fetch content"],
    ["updateContent", "Failed to update content"],
  ]) {
    const start = source.indexOf(`async function ${name}(`);
    const end = source.indexOf("\n}\n", start) + 3;
    const original = source.slice(start, end);
    assert.ok(start > 0 && end > start);
    replace(
      original,
      original
        .replace(
          "return (await parseApiResponse(",
          "const payload = await parseApiResponse(",
        )
        .replace(
          `"${message}")).item;`,
          `"${message}");\n\treturn { ...payload.item, _rev: payload._rev };`,
        ),
    );
  }
  replace(
    "\t\tenabled: !i18n || !!activeLocale\n\t});",
    `\t\tenabled: !i18n || !!activeLocale
\t});
\t// Keep the revision this editor loaded, not a background query refresh.
\tconst leonaidRevisions = React$1.useRef(new Map());
\tconst leonaidEntry = React$1.useRef("");
\tif (leonaidEntry.current !== id) {
\t\tleonaidEntry.current = id;
\t\tleonaidRevisions.current.delete(id);
\t}
\tif (rawItem && !leonaidRevisions.current.has(rawItem.id))
\t\tleonaidRevisions.current.set(rawItem.id, rawItem._rev);
\tconst leonaidSave = async (targetId, targetLocale, changes) => {
\t\tconst saved = await updateContent(collection, targetId,
\t\t\t{ ...changes, _rev: leonaidRevisions.current.get(targetId) },
\t\t\t{ locale: targetLocale });
\t\tleonaidRevisions.current.set(targetId, saved._rev);
\t\treturn saved;
\t};`,
  );
  replace(
    "mutationFn: ({ targetId, targetLocale, changes }) => updateContent(collection, targetId, changes, { locale: targetLocale }),",
    "mutationFn: ({ targetId, targetLocale, changes }) => leonaidSave(targetId, targetLocale, changes),",
  );
  replace(
    `mutationFn: ({ targetId, targetLocale, changes }) => updateContent(collection, targetId, {
\t\t\t...changes,
\t\t\tskipRevision: true
\t\t}, { locale: targetLocale }),`,
    `mutationFn: ({ targetId, targetLocale, changes }) => leonaidSave(targetId, targetLocale, {
\t\t\t...changes,
\t\t\tskipRevision: true
\t\t}),`,
  );
  replace(
    `mutationFn: () => publishContent(collection, id, { locale: rawItem?.locale ?? activeLocale }),
\t\tonSuccess: () => {`,
    `mutationFn: () => publishContent(collection, id, { locale: rawItem?.locale ?? activeLocale }),
\t\tonSuccess: async () => {
\t\t\tconst refreshed = await fetchContent(collection, id, { locale: rawItem?.locale ?? activeLocale });
\t\t\tleonaidRevisions.current.set(id, refreshed._rev);`,
  );
  return patchRepeaterEditor(patchCampaignMediaEditor(source));
}

export default function editorRevisionPatch() {
  let transformed = false;
  const require = createRequire(import.meta.url);
  const entry = require.resolve("@emdash-cms/admin");
  return {
    name: "leonaid-pinned-editor-revisions",
    hooks: {
      "astro:config:setup": async ({ updateConfig }) => {
        patchEditorSource(await readFile(entry, "utf8"));
        updateConfig({
          vite: {
            plugins: [
              {
                name: "leonaid-emdash-editor-revisions",
                enforce: "pre",
                transform(source, id) {
                  if (id.split("?")[0] !== entry) return;
                  transformed = true;
                  return { code: patchEditorSource(source), map: null };
                },
              },
            ],
          },
        });
      },
      "astro:build:done": () => {
        assert.ok(
          transformed,
          "Editor revision patch missing from production build",
        );
      },
    },
  };
}

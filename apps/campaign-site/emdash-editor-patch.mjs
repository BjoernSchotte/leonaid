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
  // Reuse the existing header affordance. A plain same-tab link preserves
  // browser history; the editor's dirty state guards document navigation.
  replace(
    '\t\t\t\t/* @__PURE__ */ jsxs(LinkButton, {\n\t\t\t\t\tvariant: "ghost",\n\t\t\t\t\tsize: "sm",\n\t\t\t\t\thref: "/",\n\t\t\t\t\texternal: true,\n\t\t\t\t\tchildren: [/* @__PURE__ */ jsx(ArrowSquareOut, { className: "h-4 w-4 me-1" }), _t({\n\t\t\t\t\t\tid: "4/SFQS",\n\t\t\t\t\t\tmessage: "View Site"\n\t\t\t\t\t})]\n\t\t\t\t}),',
    '\t\t\t\t/* @__PURE__ */ jsx("a", { href: "/admin/", className: "flex items-center rounded-md px-3 py-2 text-sm hover:bg-kumo-tint", style: { minHeight: 44 }, children: "Zurück zu LeonAid" }),',
  );
  replace(
    "\tconst isDirty = isNew || currentData !== lastSavedData;",
    `\tconst isDirty = isNew || currentData !== lastSavedData;
\tconst leonaidInitialData = React$1.useRef(currentData);
\tconst leonaidUnsaved = isNew ? currentData !== leonaidInitialData.current : isDirty;
\tReact$1.useEffect(() => {
\t\tif (collection !== "campaign_pages" || !leonaidUnsaved) return;
\t\tconst warnBeforeLeaving = (event) => {
\t\t\tevent.preventDefault();
\t\t\tevent.returnValue = "";
\t\t};
\t\twindow.addEventListener("beforeunload", warnBeforeLeaving);
\t\treturn () => window.removeEventListener("beforeunload", warnBeforeLeaving);
\t}, [collection, leonaidUnsaved]);`,
  );
  // A CMS logout must revoke the same Core session used by both surfaces.
  // Never open native EmDash auth routes or pretend a failed logout succeeded.
  replace(
    '\tconst res = await apiFetch("/_emdash/api/auth/logout?redirect=/_emdash/admin/login", {\n\t\tmethod: "POST",\n\t\tcredentials: "same-origin"\n\t});\n\tif (res.redirected) window.location.href = res.url;\n\telse window.location.href = "/_emdash/admin/login";',
    '\ttry {\n\t\tconst res = await apiFetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin", redirect: "error" });\n\t\tif (!res.ok) throw new Error("logout_failed");\n\t\twindow.location.href = "/admin/";\n\t} catch {\n\t\twindow.alert("Sign out failed. Please try again; your session may still be active.");\n\t}',
  );
  // Core owns campaign URLs. Keep the native Live View control, but never use
  // the CMS binding UUID as a public slug. Missing metadata hides the link.
  replace(
    "function Header() {",
    'function leonaidContentUrl(collection, item, urlPattern) {\n\treturn collection === "campaign_pages" ? (/^\\/campaigns\\/[a-z0-9]+(?:-[a-z0-9]+)*\\/$/.test(item?.leonaidLivePath ?? "") ? item.leonaidLivePath : null) : (item?.slug ? contentUrl(collection, item.slug, urlPattern) : null);\n}\nfunction Header() {',
  );
  replace(
    "\tconst liveViewUrl = isLive && item?.slug ? contentUrl(collection, item.slug, urlPattern) : null;",
    "\tconst liveViewUrl = isLive ? leonaidContentUrl(collection, item, urlPattern) : null;",
  );
  replace(
    'item.status === "published" && item.slug && /* @__PURE__ */ jsx(LinkButton, {\n\t\t\t\t\t\t\thref: contentUrl(collection, item.slug, urlPattern),',
    'item.status === "published" && leonaidContentUrl(collection, item, urlPattern) && /* @__PURE__ */ jsx(LinkButton, {\n\t\t\t\t\t\t\thref: leonaidContentUrl(collection, item, urlPattern),',
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
  // Publishing changes the entry's revision token, but the publish response
  // carries none. Saves issued before the refreshed token arrives wait for it
  // instead of racing with a stale token. If the refresh fails, the next
  // loaded entry supplies the token, exactly as on first load.
  replace(
    "\t\t\t{ ...changes, _rev: leonaidRevisions.current.get(targetId) },",
    "\t\t\t{ ...changes, _rev: await leonaidRevisions.current.get(targetId) },",
  );
  replace(
    `mutationFn: () => publishContent(collection, id, { locale: rawItem?.locale ?? activeLocale }),
\t\tonSuccess: () => {`,
    `mutationFn: () => publishContent(collection, id, { locale: rawItem?.locale ?? activeLocale }),
\t\tonSuccess: async () => {
\t\t\tconst refreshing = fetchContent(collection, id, { locale: rawItem?.locale ?? activeLocale }).then((refreshed) => refreshed._rev);
\t\t\tleonaidRevisions.current.set(id, refreshing);
\t\t\trefreshing.then((rev) => {
\t\t\t\tif (leonaidRevisions.current.get(id) === refreshing) leonaidRevisions.current.set(id, rev);
\t\t\t}, () => {
\t\t\t\tif (leonaidRevisions.current.get(id) === refreshing) leonaidRevisions.current.delete(id);
\t\t\t});`,
  );
  // A content or draft refetch started before this autosave was stored (for
  // example the one a publish triggers) may answer after it and would put the
  // older entry back. Cancel such fetches before patching the saved state in.
  replace(
    "\t\tonSuccess: (savedItem, variables) => {\n\t\t\trecordAutosaveCompletion(variables.targetId);\n\t\t\tpatchAutosaveQueries(queryClient, {",
    `\t\tonSuccess: async (savedItem, variables) => {
\t\t\tawait queryClient.cancelQueries({ queryKey: ["content", collection, variables.targetId] });
\t\t\tif (savedItem.draftRevisionId) await queryClient.cancelQueries({ queryKey: ["revision", savedItem.draftRevisionId] });
\t\t\trecordAutosaveCompletion(variables.targetId);
\t\t\tpatchAutosaveQueries(queryClient, {`,
  );
  // Upstream re-syncs the whole form whenever the loaded entry changes
  // (autosave response, publish, background refetch) and so discards input
  // typed while that request was in flight. With unsaved input, merge per
  // field instead: a field the user changed since the last sync keeps the
  // local value, every other field takes the server value. The form then
  // stays dirty, so autosave persists the kept input. Without unsaved input
  // the upstream full reset applies (discard draft, restore revision).
  replace(
    "\tconst [previousItemId, setPreviousItemId] = React$1.useState(item?.id ?? null);\n\tif (item && item.id !== previousItemId) {\n\t\tsetPreviousItemId(item.id);",
    '\tconst leonaidSynced = React$1.useRef({ data: item?.data || {}, slug: item?.slug || "" });\n\tconst [previousItemId, setPreviousItemId] = React$1.useState(item?.id ?? null);\n\tif (item && item.id !== previousItemId) {\n\t\tleonaidSynced.current = { data: item.data, slug: item.slug || "" };\n\t\tsetPreviousItemId(item.id);',
  );
  replace(
    '\tReact$1.useEffect(() => {\n\t\tif (item) {\n\t\t\tconst nextBylines = resolveEditorBylines(item).explicitCredits;\n\t\t\tsetFormData(item.data);\n\t\t\tsetSlug(item.slug || "");\n\t\t\tsetSlugTouched(!!item.slug);',
    `\tReact$1.useEffect(() => {
\t\tif (item) {
\t\t\tconst nextBylines = resolveEditorBylines(item).explicitCredits;
\t\t\tconst base = leonaidSynced.current;
\t\t\tleonaidSynced.current = { data: item.data, slug: item.slug || "" };
\t\t\tconst local = formDataRef.current;
\t\t\tconst unsaved = serializeEditorState({ data: local, slug: slugRef.current, bylines: activeBylines }) !== lastSavedData;
\t\t\tconst edited = (a, b) => !Object.is(a, b) && JSON.stringify(a) !== JSON.stringify(b);
\t\t\tconst merged = { ...item.data };
\t\t\tif (unsaved) for (const key of new Set([...Object.keys(base.data), ...Object.keys(local)])) {
\t\t\t\tif (!edited(local[key], base.data[key])) continue;
\t\t\t\tif (Object.hasOwn(local, key)) merged[key] = local[key];
\t\t\t\telse delete merged[key];
\t\t\t}
\t\t\tconst keepSlug = unsaved && slugRef.current !== base.slug;
\t\t\tsetFormData(merged);
\t\t\tsetSlug(keepSlug ? slugRef.current : item.slug || "");
\t\t\tif (!keepSlug) setSlugTouched(!!item.slug);`,
  );
  // Upstream mounts the editor as soon as the live item arrives and merges the
  // draft revision one request later. The merge resets the form to the draft,
  // silently discarding anything typed in between. Mount the editor once per
  // entry only after its draft has loaded (or failed), so the first editable
  // form already shows the draft. Later draft revisions keep the editor
  // mounted; a failed draft fetch keeps upstream's live-data fallback.
  replace(
    "\tconst { data: draftRevision } = useQuery({",
    "\tconst { data: draftRevision, isLoading: leonaidDraftLoading } = useQuery({",
  );
  replace(
    "\tif (isLoading) return /* @__PURE__ */ jsx(LoadingScreen, {});\n\treturn /* @__PURE__ */ jsx(ContentEditor, {\n\t\tcollection,\n\t\tcollectionLabel:",
    "\tif (rawItem && (!rawItem.draftRevisionId || !leonaidDraftLoading)) leonaidDraftEntry.current = id;\n\tif (isLoading || (rawItem && leonaidDraftEntry.current !== id)) return /* @__PURE__ */ jsx(LoadingScreen, {});\n\treturn /* @__PURE__ */ jsx(ContentEditor, {\n\t\tcollection,\n\t\tcollectionLabel:",
  );
  replace(
    "\tconst item = React$1.useMemo(() => {\n\t\tif (!rawItem) return void 0;\n\t\tif (!draftRevision?.data) return rawItem;",
    '\tconst leonaidDraftEntry = React$1.useRef("");\n\tconst item = React$1.useMemo(() => {\n\t\tif (!rawItem) return void 0;\n\t\tif (!draftRevision?.data) return rawItem;',
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
                  return {
                    code:
                      'import "/src/scrollbars.css";\n' +
                      patchEditorSource(source),
                    map: null,
                  };
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

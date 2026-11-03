import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { patchCampaignMediaEditor } from "./emdash-media-editor-patch.mjs";
import { patchRepeaterEditor } from "./emdash-repeater-editor-patch.mjs";

export const upstreamEditorSha256 =
  "f4a2397269b973e35e6deecb16fa8591a38798c734b6ac4d9546b3cc8c8171b3";

// LeonAid seams in the published EmDash 1.4 admin client. EmDash 1.x itself
// transports the `_rev` revision token on every save, publish, unpublish and
// discard, keeps a dirty form when the entry refetches, and guards unsaved
// edits with its own leave prompt. Authentication and concurrency enforcement
// remain server-side. No fetch interception, request fabrication or
// substitute editor is introduced.
export function patchEditorSource(source) {
  assert.equal(
    createHash("sha256").update(source).digest("hex"),
    upstreamEditorSha256,
    "EmDash editor source changed; re-review the LeonAid editor patch",
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
  // A CMS logout must revoke the same Core session used by both surfaces.
  // Never open native EmDash auth routes or pretend a failed logout succeeded.
  replace(
    '\tconst res = await apiFetch("/_emdash/api/auth/logout?redirect=/_emdash/admin/login", {\n\t\tmethod: "POST",\n\t\tcredentials: "same-origin"\n\t});\n\tif (res.redirected) window.location.href = res.url;\n\telse window.location.href = "/_emdash/admin/login";',
    '\ttry {\n\t\tconst res = await apiFetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin", redirect: "error" });\n\t\tif (!res.ok) throw new Error("logout_failed");\n\t\twindow.location.href = "/admin/";\n\t} catch {\n\t\twindow.alert("Sign out failed. Please try again; your session may still be active.");\n\t}',
  );
  // Core owns campaign URLs. Keep the native Live View controls, but never use
  // the CMS binding UUID as a public slug. Missing metadata hides the link.
  replace(
    "function Header() {",
    'function leonaidContentUrl(collection, item, urlPattern, options) {\n\treturn collection === "campaign_pages" ? (/^\\/campaigns\\/[a-z0-9]+(?:-[a-z0-9]+)*\\/$/.test(item?.leonaidLivePath ?? "") ? item.leonaidLivePath : null) : (item?.slug ? contentUrl(collection, item.slug, urlPattern, options) : null);\n}\nfunction Header() {',
  );
  replace(
    "\tconst liveViewUrl = isLive && item?.slug ? contentUrl(collection, item.slug, urlPattern, {\n\t\tlocale: item.locale,\n\t\ti18n,\n\t\tid: item.id,\n\t\tdate: item.publishedAt\n\t}) : null;",
    "\tconst liveViewUrl = isLive ? leonaidContentUrl(collection, item, urlPattern, {\n\t\tlocale: item.locale,\n\t\ti18n,\n\t\tid: item.id,\n\t\tdate: item.publishedAt\n\t}) : null;",
  );
  replace(
    '\t\t\t\t\t\titem.status === "published" && item.slug && /* @__PURE__ */ jsx(DropdownMenu.LinkItem, {\n\t\t\t\t\t\t\tcloseOnClick: true,\n\t\t\t\t\t\t\ticon: /* @__PURE__ */ jsx(ArrowSquareOut, {\n\t\t\t\t\t\t\t\tclassName: "me-2 size-4",\n\t\t\t\t\t\t\t\t"aria-hidden": "true"\n\t\t\t\t\t\t\t}),\n\t\t\t\t\t\t\thref: contentUrl(collection, item.slug, urlPattern, {',
    '\t\t\t\t\t\titem.status === "published" && leonaidContentUrl(collection, item, urlPattern) && /* @__PURE__ */ jsx(DropdownMenu.LinkItem, {\n\t\t\t\t\t\t\tcloseOnClick: true,\n\t\t\t\t\t\t\ticon: /* @__PURE__ */ jsx(ArrowSquareOut, {\n\t\t\t\t\t\t\t\tclassName: "me-2 size-4",\n\t\t\t\t\t\t\t\t"aria-hidden": "true"\n\t\t\t\t\t\t\t}),\n\t\t\t\t\t\t\thref: leonaidContentUrl(collection, item, urlPattern, {',
  );
  // Firefox can retain the old selection when an unfocused editor receives a
  // click in an empty paragraph. Use the supported ProseMirror click seam;
  // preserve modifier/drag/keyboard behavior and never modify document content.
  replace(
    "\tconst editorProps = React$1.useMemo(() => ({\n\t\tscrollThreshold: isDocument ? {",
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
\t\t},
\t\tscrollThreshold: isDocument ? {`,
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
    "\tconst [formData, setFormData] = React$1.useState(() => item?.data ?? (isNew ? defaultFieldValues(fields) : {}));",
    '\tconst leonaidInitialAction = isNew && collection === "campaign_pages" ? leonaidActionId : void 0;\n\tconst [formData, setFormData] = React$1.useState(() => item?.data ?? (isNew ? { ...defaultFieldValues(fields), ...(leonaidInitialAction ? { action_id: leonaidInitialAction } : {}) } : {}));',
  );
  replace(
    '\tconst [slug, setSlug] = React$1.useState(item?.slug || "");\n\tconst [slugTouched, setSlugTouched] = React$1.useState(!!item?.slug);',
    '\tconst [slug, setSlug] = React$1.useState(item?.slug || leonaidInitialAction || "");\n\tconst [slugTouched, setSlugTouched] = React$1.useState(!!item?.slug || !!leonaidInitialAction);',
  );
  // Upstream mounts the editor as soon as the live item arrives and merges the
  // draft revision one request later. 1.x no longer resets a dirty form when
  // the draft arrives, so input typed in between survives, but the form then
  // never takes the draft's other values and the next save writes live data
  // plus the new input over the draft. Mount the editor once per entry only
  // after its draft has loaded (or failed), so the first editable form already
  // shows the draft. Later draft revisions keep the editor mounted; a failed
  // draft fetch keeps upstream's live-data fallback.
  replace(
    "\tconst { data: draftRevision } = useQuery({",
    "\tconst { data: draftRevision, isLoading: leonaidDraftLoading } = useQuery({",
  );
  replace(
    "\tif (isLoading) return /* @__PURE__ */ jsx(LoadingScreen, {});\n\tif (itemError && !rawItem) {",
    "\tif (rawItem && (!rawItem.draftRevisionId || !leonaidDraftLoading)) leonaidDraftEntry.current = id;\n\tif (isLoading || (rawItem && leonaidDraftEntry.current !== id)) return /* @__PURE__ */ jsx(LoadingScreen, {});\n\tif (itemError && !rawItem) {",
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

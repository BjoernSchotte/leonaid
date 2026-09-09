import assert from "node:assert/strict";
import "./editorial-contract-proof.mjs";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { patchAuthSource } from "../../apps/campaign-site/emdash-auth-patch.mjs";
import { patchEditorSource } from "../../apps/campaign-site/emdash-editor-patch.mjs";
import {
  campaignMediaFileKey,
  campaignMediaRoute,
} from "../../apps/campaign-site/src/auth/campaign-media-routes.mjs";
import {
  contentHandlerEntry,
  patchContentLogs,
} from "../../apps/campaign-site/emdash-content-log-patch.mjs";

const require = createRequire(import.meta.url);
const source = await readFile(
  require.resolve("emdash/middleware/auth"),
  "utf8",
);
const patched = patchAuthSource(source);
assert.notEqual(patched, source);
// Exercise integrity against real installed source, not a replacement module.
for (const changed of [
  source + "\n",
  source.replace("getUserByEmail", "getUserById"),
  patched,
]) {
  assert.throws(() => patchAuthSource(changed), /EmDash auth source changed/);
}
console.log(
  "emdash-auth-patch: OK: exact installed source accepted; byte drift, semantic drift and double application rejected",
);
const editor = await readFile(require.resolve("@emdash-cms/admin"), "utf8");
const revisioned = patchEditorSource(editor);
assert.notEqual(revisioned, editor);
const header = revisioned.slice(
  revisioned.indexOf("function Header()"),
  revisioned.indexOf("//#region src/components/WelcomeModal.tsx"),
);
assert.ok(header.includes('href: "/admin/"'));
assert.ok(header.includes('jsx("a", { href: "/admin/"'));
assert.ok(header.includes('children: "Zurück zu LeonAid"'));
assert.ok(!header.includes("external: true"));
assert.ok(!header.includes('message: "View Site"'));
const guard = revisioned.match(
  /React\$1\.useEffect\(\(\) => \{\n\t\tif \(collection !== "campaign_pages" \|\| !leonaidUnsaved\)[\s\S]+?\}, \[collection, leonaidUnsaved\]\);/,
);
assert.ok(guard);
assert.ok(
  revisioned.includes(
    "const leonaidInitialData = React$1.useRef(currentData);",
  ),
);
// New forms remain saveable, but only actual edits warrant a leave warning.
const unsavedExpression = revisioned.match(/const leonaidUnsaved = ([^\n]+);/);
assert.ok(unsavedExpression);
const hasUnsaved = new Function(
  "isNew",
  "currentData",
  "leonaidInitialData",
  "isDirty",
  `return ${unsavedExpression[1]};`,
);
for (const [isNew, current, initial, dirty, expected] of [
  [true, "prefilled", "prefilled", true, false],
  [true, "edited", "prefilled", true, true],
  [true, "prefilled", "prefilled", true, false],
  [false, "saved", "loaded", false, false],
  [false, "edited", "loaded", true, true],
])
  assert.equal(
    hasUnsaved(isNew, current, { current: initial }, dirty),
    expected,
  );
for (const [collection, dirty, expected] of [
  ["campaign_pages", true, 1],
  ["campaign_pages", false, 0],
  ["posts", true, 0],
]) {
  const listeners = new Map();
  let cleanup;
  new Function("React$1", "window", "collection", "leonaidUnsaved", guard[0])(
    {
      useEffect: (effect) => {
        cleanup = effect();
      },
    },
    {
      addEventListener: (name, listener) => listeners.set(name, listener),
      removeEventListener: (name, listener) => {
        assert.equal(listeners.get(name), listener);
        listeners.delete(name);
      },
    },
    collection,
    dirty,
  );
  assert.equal(listeners.size, expected);
  if (expected) {
    let prevented = false;
    const event = {
      preventDefault: () => {
        prevented = true;
      },
      returnValue: null,
    };
    listeners.get("beforeunload")(event);
    assert.ok(prevented);
    assert.equal(event.returnValue, "");
    cleanup();
    assert.equal(listeners.size, 0);
  }
}
const logout = revisioned.slice(
  revisioned.indexOf("async function handleLogout()"),
  revisioned.indexOf("function Header()"),
);
assert.ok(logout.includes('apiFetch("/api/v1/auth/logout"'));
assert.ok(logout.includes('redirect: "error"'));
assert.ok(logout.includes('if (!res.ok) throw new Error("logout_failed")'));
assert.ok(logout.includes('window.location.href = "/admin/"'));
assert.ok(logout.includes("window.alert("));
assert.ok(!logout.includes("/_emdash/api/auth/logout"));
const liveViewExpression = revisioned.match(/const liveViewUrl = ([^\n]+);/);
assert.ok(liveViewExpression);
const urlFunction = revisioned.match(/function leonaidContentUrl\([^]*?\n\}/);
assert.ok(urlFunction);
assert.ok(
  revisioned.includes(
    'item.status === "published" && leonaidContentUrl(collection, item, urlPattern)',
  ),
);
assert.ok(
  revisioned.includes("href: leonaidContentUrl(collection, item, urlPattern)"),
);
const liveView = new Function(
  "collection",
  "isLive",
  "item",
  "contentUrl",
  "urlPattern",
  `${urlFunction[0]}\nreturn ${liveViewExpression[1]};`,
);
const canonical = "/campaigns/krapfentaxi-2026/";
assert.equal(
  liveView("campaign_pages", true, { leonaidLivePath: canonical }),
  canonical,
);
assert.equal(
  liveView("campaign_pages", false, { leonaidLivePath: canonical }),
  null,
);
for (const path of [
  undefined,
  "https://evil.invalid/",
  "//evil.invalid/",
  "/campaigns/../admin/",
  "/campaigns/a/?preview=1",
  "/campaign_pages/binding-id",
]) {
  assert.equal(
    liveView("campaign_pages", true, { leonaidLivePath: path }),
    null,
  );
}
const repeater = revisioned.slice(
  revisioned.indexOf("function RepeaterField("),
  revisioned.indexOf("function SubFieldInput("),
);
assert.ok(
  repeater.includes(
    "useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })",
  ),
);
assert.ok(
  repeater.includes(
    "useSensor(PointerSensor, { activationConstraint: { distance: 6 } })",
  ),
);
assert.ok(repeater.includes("ref: setActivatorNodeRef"));
assert.ok(repeater.includes('"aria-expanded": !isCollapsed'));
assert.ok(repeater.includes('id: "2BPVq8", message: "Reorder {0}"'));
assert.ok(
  repeater.includes("emitChange(arrayMove(items, oldIndex, newIndex))"),
);
assert.ok(revisioned.includes("handleClick(view, _position, event)"));
assert.ok(revisioned.includes("resolved.parent.content.size !== 0"));
assert.ok(
  revisioned.includes(
    "event.shiftKey || event.ctrlKey || event.metaKey || event.altKey",
  ),
);
assert.ok(
  revisioned.includes("TextSelection.create(view.state.doc, position)"),
);
assert.ok(revisioned.includes("React$1.useContext(LeonAidMediaCampaign)"));
assert.ok(revisioned.includes('"media",\n\t\tcampaign,'));
assert.ok(
  revisioned.includes(
    "required: subField.required,\n\t\t\tallowedMimeTypes: subField.validation?.allowedMimeTypes",
  ),
);
const mediaKey =
  "campaigns/20000000-0000-4000-8000-000000000001/30000000-0000-4000-8000-000000000001.png";
for (const representation of [mediaKey, encodeURIComponent(mediaKey)]) {
  const path = `/_emdash/api/media/file/${representation}`;
  assert.equal(campaignMediaFileKey(path), mediaKey);
  assert.equal(campaignMediaRoute(path, "GET"), "file");
  assert.equal(campaignMediaRoute(path, "POST"), null);
}
for (const representation of [
  encodeURIComponent(encodeURIComponent(mediaKey)),
  encodeURIComponent(mediaKey).replaceAll("%2F", "%2f"),
  mediaKey.replace("/", "%2F"),
  "%",
  "../secret",
  `${mediaKey}/extra`,
  mediaKey.replace("campaigns", "%63ampaigns"),
]) {
  assert.equal(
    campaignMediaFileKey(`/_emdash/api/media/file/${representation}`),
    null,
  );
}
for (const changed of [
  editor + "\n",
  editor.replace("skipRevision", "skipHistory"),
  revisioned,
]) {
  assert.throws(
    () => patchEditorSource(changed),
    /EmDash editor source changed/,
  );
}
console.log(
  "emdash-editor-patch: OK: exact published client accepted; drift and double application rejected",
);
const handlers = await readFile(contentHandlerEntry(), "utf8");
const sanitized = patchContentLogs(handlers);
assert.notEqual(sanitized, handlers);
assert.equal([...sanitized.matchAll(/console\.error\(/g)].length, 21);
assert.equal(
  [...sanitized.matchAll(/console\.error\("[^"\n]+"\);/g)].length,
  21,
);
for (const changed of [
  handlers + "\n",
  handlers.replace("Content create error", "Changed create error"),
  sanitized,
]) {
  assert.throws(
    () => patchContentLogs(changed),
    /EmDash content source changed/,
  );
}
console.log(
  "emdash-content-log-patch: OK: all 21 fixed signals retained without exception objects or item identifiers; source drift and double application denied",
);

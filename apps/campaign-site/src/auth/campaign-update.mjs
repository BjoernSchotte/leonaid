import { getCampaignContent } from "./campaign-content.mjs";

const denied = () => ({
  success: /** @type {const} */ (false),
  error: { code: "FORBIDDEN", message: "Campaign update denied" },
});

// First admitted editor mutation: title draft updates. Rich editorial fields,
// media, mutable metadata and creation stay closed until their own proofs.
// The caller retains the ORIGINAL runtime updater (schema, hooks and revisions).
export async function authorizeCampaignUpdate(
  database,
  profile,
  collection,
  id,
  body,
) {
  const existing = await getCampaignContent(database, profile, collection, id);
  if (!existing.success) return existing;
  if (!body || typeof body !== "object" || Array.isArray(body)) return denied();
  if (
    Object.entries(body).some(
      ([key, value]) =>
        value !== undefined &&
        !["data", "_rev", "slug", "locale", "skipRevision"].includes(key),
    )
  )
    return denied();
  if (typeof body._rev !== "string" || !body._rev || body._rev.length > 512)
    return denied();
  // The native editor echoes the slug on every save. It is not a URL editor:
  // Core owns canonical addresses; a changed CMS slug is still denied.
  if (body.slug !== undefined && body.slug !== existing.data.item.slug)
    return denied();
  // The upstream HTTP route forwards the editor's locale query parameter.
  // Allow only an echo of this exact stored entry, never a translation switch.
  if (body.locale !== undefined && body.locale !== existing.data.item.locale)
    return denied();
  if (body.skipRevision !== undefined && typeof body.skipRevision !== "boolean")
    return denied();
  const data = body.data;
  if (
    !data ||
    typeof data !== "object" ||
    Array.isArray(data) ||
    Object.keys(data).some((key) => !["title", "action_id"].includes(key)) ||
    typeof data.title !== "string" ||
    !data.title.trim() ||
    data.title.length > 400
  )
    return denied();
  if (
    Object.hasOwn(data, "action_id") &&
    data.action_id !== existing.data.item.data.action_id
  )
    return denied();
  return null;
}

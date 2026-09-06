import { sql } from "kysely";
import { MediaRepository } from "emdash";
import { randomUUID } from "node:crypto";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ulid = /^[0-9A-HJKMNP-TV-Z]{26}$/;
const versionName = "leonaid:campaign_media_version";
const guardBody = `BEGIN
  IF TG_OP = 'DELETE' THEN
    IF EXISTS (SELECT 1 FROM public.media WHERE id = OLD.media_id) THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='campaign_media_binding_immutable';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.media_id IS DISTINCT FROM NEW.media_id OR OLD.action_id IS DISTINCT FROM NEW.action_id THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='campaign_media_binding_immutable';
  END IF;
  RETURN NEW;
END;`;

// These primitives require a fresh server-validated Core profile. They neither
// authenticate a request nor admit upstream media/file/preview HTTP routes.
function requireAction(profile, actionId) {
  if (
    typeof actionId !== "string" ||
    !uuid.test(actionId) ||
    !profile ||
    !Array.isArray(profile.globalRoles) ||
    !Array.isArray(profile.actionMemberships) ||
    (!profile.globalRoles.includes("system_admin") &&
      !profile.actionMemberships.some(
        (membership) =>
          membership.actionId === actionId &&
          membership.role === "charity_admin",
      ))
  )
    throw new Error("campaign_media_access_denied");
}

async function requireDatabase(database) {
  const { rows } =
    await sql`SELECT current_database() AS db, current_user AS role`.execute(
      database,
    );
  if (rows[0]?.db !== "emdash" || rows[0]?.role !== "emdash")
    throw new Error("campaign_media_database_required");
}

// Operator-only schema extension, independent of the editorial field version.
// Existing unbound media stays inaccessible; never infer a campaign from author,
// filename, content hash, folder, or references in an editorial document.
export async function installCampaignMedia(database) {
  await requireDatabase(database);
  return database.transaction().execute(async (transaction) => {
    await sql`SET LOCAL lock_timeout = '3s'`.execute(transaction);
    await sql`SET LOCAL statement_timeout = '5s'`.execute(transaction);
    await sql`SELECT pg_advisory_xact_lock(724381905)`.execute(transaction);
    const version = await transaction
      .selectFrom("options")
      .select("value")
      .where("name", "=", versionName)
      .executeTakeFirst();
    if (version) {
      await requireCampaignMedia(transaction);
      return { created: false };
    }
    // No IF NOT EXISTS/repair: partial or unknown installations fail closed.
    await sql`CREATE TABLE public.leonaid_campaign_media (
      media_id text PRIMARY KEY REFERENCES public.media(id) ON DELETE CASCADE,
      action_id text NOT NULL CHECK (action_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    )`.execute(transaction);
    await sql`CREATE INDEX leonaid_campaign_media_action ON public.leonaid_campaign_media(action_id, media_id)`.execute(
      transaction,
    );
    await sql
      .raw(
        `CREATE FUNCTION public.leonaid_campaign_media_guard() RETURNS trigger
      LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $guard$${guardBody}$guard$`,
      )
      .execute(transaction);
    await sql`CREATE TRIGGER leonaid_campaign_media_guard BEFORE UPDATE OR DELETE ON public.leonaid_campaign_media
      FOR EACH ROW EXECUTE FUNCTION public.leonaid_campaign_media_guard()`.execute(
      transaction,
    );
    await transaction
      .insertInto("options")
      .values({ name: versionName, value: "1" })
      .execute();
    await requireCampaignMedia(transaction);
    return { created: true };
  });
}

export async function requireCampaignMedia(database) {
  await requireDatabase(database);
  const version = await database
    .selectFrom("options")
    .select("value")
    .where("name", "=", versionName)
    .executeTakeFirst();
  if (version?.value !== "1")
    throw new Error("campaign_media_version_mismatch");
  const { rows } = await sql`
    SELECT p.prosrc, p.prosecdef, p.proconfig, t.tgenabled, t.tgtype,
      t.tgqual IS NULL AS unconditional, t.tgattr::text AS attributes
    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    JOIN pg_trigger t ON t.tgfoid=p.oid
    WHERE n.nspname='public' AND p.proname='leonaid_campaign_media_guard'
      AND p.pronargs=0 AND p.prorettype='trigger'::regtype
      AND p.proowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)
      AND t.tgrelid=to_regclass('public.leonaid_campaign_media')
      AND t.tgname='leonaid_campaign_media_guard' AND NOT t.tgisinternal
  `.execute(database);
  const row = rows[0];
  if (
    rows.length !== 1 ||
    row.prosrc !== guardBody ||
    row.prosecdef ||
    JSON.stringify(row.proconfig) !==
      JSON.stringify(["search_path=pg_catalog"]) ||
    row.tgenabled !== "O" ||
    row.tgtype !== 27 ||
    !row.unconditional ||
    row.attributes !== ""
  )
    throw new Error("campaign_media_guard_mismatch");
  const constraints = await sql`
    SELECT conname, pg_get_constraintdef(oid) AS definition, convalidated, condeferrable
    FROM pg_constraint WHERE conrelid='public.leonaid_campaign_media'::regclass
    ORDER BY conname
  `.execute(database);
  const expected = [
    [
      "leonaid_campaign_media_action_id_check",
      "CHECK ((action_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text))",
    ],
    [
      "leonaid_campaign_media_media_id_fkey",
      "FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE",
    ],
    ["leonaid_campaign_media_pkey", "PRIMARY KEY (media_id)"],
  ];
  if (
    constraints.rows.length !== expected.length ||
    constraints.rows.some(
      (item, index) =>
        item.conname !== expected[index][0] ||
        item.definition !== expected[index][1] ||
        !item.convalidated ||
        item.condeferrable,
    )
  )
    throw new Error("campaign_media_constraints_mismatch");
  const columns =
    await sql`SELECT attname, attnotnull, format_type(atttypid, atttypmod) AS type
    FROM pg_attribute WHERE attrelid='public.leonaid_campaign_media'::regclass
      AND attnum>0 AND NOT attisdropped ORDER BY attnum`.execute(database);
  if (
    JSON.stringify(columns.rows) !==
    JSON.stringify([
      { attname: "media_id", attnotnull: true, type: "text" },
      { attname: "action_id", attnotnull: true, type: "text" },
    ])
  )
    throw new Error("campaign_media_columns_mismatch");
}

function scoped(database, actionId) {
  return database
    .selectFrom("leonaid_campaign_media")
    .innerJoin("media", "media.id", "leonaid_campaign_media.media_id")
    .where("leonaid_campaign_media.action_id", "=", actionId);
}

// The upload coordinator rechecks Core authority before calling this function.
// Keys are generated here, never accepted from request data or original names.
export async function createCampaignPendingMedia(
  database,
  profile,
  actionId,
  input,
) {
  requireAction(profile, actionId);
  if (
    !input ||
    Object.keys(input).some(
      (key) => !["filename", "mimeType", "size", "authorId"].includes(key),
    ) ||
    !["image/jpeg", "image/png", "image/webp"].includes(input.mimeType) ||
    !Number.isSafeInteger(input.size) ||
    input.size < 1 ||
    input.size > 8 * 1024 * 1024 ||
    typeof input.filename !== "string" ||
    input.filename.length > 200 ||
    !input.filename.trim() ||
    /[\u0000-\u001f\u007f/\\]/.test(input.filename) ||
    typeof input.authorId !== "string" ||
    !ulid.test(input.authorId)
  )
    throw new Error("campaign_media_input_invalid");
  await requireCampaignMedia(database);
  return database.transaction().execute(async (transaction) => {
    const extension = {
      "image/jpeg": "jpg",
      "image/png": "png",
      "image/webp": "webp",
    }[input.mimeType];
    const item = await new MediaRepository(transaction).createPending({
      ...input,
      storageKey: `campaigns/${actionId}/${randomUUID()}.${extension}`,
    });
    await transaction
      .insertInto("leonaid_campaign_media")
      .values({ media_id: item.id, action_id: actionId })
      .execute();
    return item;
  });
}

export async function getCampaignMedia(database, profile, actionId, id) {
  requireAction(profile, actionId);
  await requireCampaignMedia(database);
  if (typeof id !== "string" || !ulid.test(id)) return null;
  return database.transaction().execute(async (transaction) => {
    const permitted = await scoped(transaction, actionId)
      .select("media.id")
      .where("media.id", "=", id)
      .forShare()
      .executeTakeFirst();
    return permitted
      ? new MediaRepository(transaction).findById(permitted.id)
      : null;
  });
}

// No global deduplication: identical bytes in another campaign must reveal
// neither its media identity nor whether that campaign has uploaded them.
export async function findCampaignMediaByHash(
  database,
  profile,
  actionId,
  hash,
) {
  requireAction(profile, actionId);
  await requireCampaignMedia(database);
  if (typeof hash !== "string" || !/^[0-9a-f]{64}$/.test(hash))
    throw new Error("campaign_media_input_invalid");
  return database.transaction().execute(async (transaction) => {
    const permitted = await scoped(transaction, actionId)
      .select("media.id")
      .where("media.status", "=", "ready")
      .where("media.content_hash", "=", hash)
      .orderBy("media.id")
      .limit(1)
      .forShare()
      .executeTakeFirst();
    return permitted
      ? new MediaRepository(transaction).findById(permitted.id)
      : null;
  });
}

export async function listCampaignMedia(
  database,
  profile,
  actionId,
  parameters = {},
) {
  requireAction(profile, actionId);
  await requireCampaignMedia(database);
  const { limit = 30, cursor, q = "" } = parameters;
  if (
    Object.keys(parameters).some(
      (key) => !["limit", "cursor", "q"].includes(key),
    ) ||
    !Number.isSafeInteger(limit) ||
    limit < 1 ||
    limit > 100 ||
    (cursor !== undefined &&
      (typeof cursor !== "string" || !ulid.test(cursor))) ||
    typeof q !== "string" ||
    q.length > 200
  )
    throw new Error("campaign_media_input_invalid");
  return database
    .transaction()
    .setIsolationLevel("repeatable read")
    .execute(async (transaction) => {
      const query = scoped(transaction, actionId)
        .where("media.status", "=", "ready")
        .where(sql`strpos(lower(media.filename), lower(${q}))`, ">", 0);
      const count = await query
        .select((eb) => eb.fn.count("media.id").as("count"))
        .executeTakeFirstOrThrow();
      let page = query
        .select("media.id")
        .orderBy("media.id", "desc")
        .limit(limit + 1);
      if (cursor !== undefined) page = page.where("media.id", "<", cursor);
      const rows = await page.forShare().execute();
      const ids = rows.slice(0, limit);
      const repository = new MediaRepository(transaction);
      return {
        items: await Promise.all(ids.map(({ id }) => repository.findById(id))),
        totalCount: Number(count.count),
        nextCursor: rows.length > limit ? ids.at(-1).id : undefined,
      };
    });
}

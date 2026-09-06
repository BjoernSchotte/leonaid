import { sql } from "kysely";

const uuid = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$";
const guards = [
  {
    name: "leonaid_campaign_binding",
    table: "ec_campaign_pages",
    body: `BEGIN
  IF NEW.action_id IS NULL OR NEW.action_id !~ '${uuid}' THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='campaign_binding_invalid';
  END IF;
  IF TG_OP = 'UPDATE' AND (OLD.action_id IS DISTINCT FROM NEW.action_id OR OLD.id IS DISTINCT FROM NEW.id) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='campaign_binding_immutable';
  END IF;
  RETURN NEW;
END;`,
  },
  {
    name: "leonaid_campaign_revision_binding",
    table: "revisions",
    body: `DECLARE binding text;
BEGIN
  IF TG_OP = 'UPDATE' AND (OLD.collection = 'campaign_pages' OR NEW.collection = 'campaign_pages')
    AND (OLD.collection IS DISTINCT FROM NEW.collection OR OLD.entry_id IS DISTINCT FROM NEW.entry_id OR OLD.id IS DISTINCT FROM NEW.id) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='campaign_revision_parent_immutable';
  END IF;
  IF NEW.collection = 'campaign_pages' THEN
    SELECT action_id INTO binding FROM public.ec_campaign_pages WHERE id = NEW.entry_id FOR SHARE;
    IF binding IS NULL OR (NEW.data::jsonb ->> 'action_id') IS DISTINCT FROM binding THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='campaign_revision_binding_invalid';
    END IF;
  END IF;
  RETURN NEW;
END;`,
  },
];

async function requireCmsDatabase(database) {
  const result =
    await sql`SELECT current_database() AS db, current_user AS role`.execute(
      database,
    );
  if (result.rows[0]?.db !== "emdash" || result.rows[0]?.role !== "emdash") {
    throw new Error("campaign_binding_database_required");
  }
}

// Runtime is check-only. Missing, disabled or altered guards must not silently
// permit writes. These are application invariants, not a sandbox against the
// trusted DB owner executing arbitrary DDL.
export async function requireCampaignBindings(database) {
  await requireCmsDatabase(database);
  for (const guard of guards) {
    const result = await sql`
      SELECT p.prosrc, p.prosecdef, p.proconfig, t.tgenabled, t.tgtype,
        t.tgqual IS NULL AS unconditional, t.tgattr::text AS attributes
      FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      JOIN pg_trigger t ON t.tgfoid=p.oid
      WHERE n.nspname='public' AND p.proname=${guard.name}
        AND p.pronargs=0 AND p.prorettype='trigger'::regtype
        AND p.proowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)
        AND t.tgrelid=to_regclass(${`public.${guard.table}`})
        AND t.tgname=${guard.name} AND NOT t.tgisinternal
    `.execute(database);
    const row = result.rows[0];
    if (
      result.rows.length !== 1 ||
      row.prosrc !== guard.body ||
      row.prosecdef ||
      JSON.stringify(row.proconfig) !==
        JSON.stringify(["search_path=pg_catalog"]) ||
      row.tgenabled !== "O" ||
      row.tgtype !== 23 ||
      !row.unconditional ||
      row.attributes !== ""
    ) {
      throw new Error("campaign_binding_guard_mismatch");
    }
  }
  const unique = await sql`
    SELECT c.convalidated, c.condeferrable, c.condeferred,
      c.conkey::text = ('{' || a.attnum::text || '}') AS exact_key,
      i.indisunique, i.indisvalid, i.indisready, i.indimmediate,
      i.indpred IS NULL AND i.indexprs IS NULL AS unconditional,
      i.indnatts = 1 AND i.indnkeyatts = 1 AS single_column
    FROM pg_constraint c JOIN pg_index i ON i.indexrelid=c.conindid
    JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attname='action_id'
    WHERE c.conrelid='public.ec_campaign_pages'::regclass
      AND c.conname='leonaid_campaign_action_unique' AND c.contype='u'
  `.execute(database);
  const row = unique.rows[0];
  if (
    unique.rows.length !== 1 ||
    !row.convalidated ||
    row.condeferrable ||
    row.condeferred ||
    !row.exact_key ||
    !row.indisunique ||
    !row.indisvalid ||
    !row.indisready ||
    !row.indimmediate ||
    !row.unconditional ||
    !row.single_column
  ) {
    throw new Error("campaign_binding_unique_mismatch");
  }
  const version = await database
    .selectFrom("options")
    .select("value")
    .where("name", "=", "leonaid:campaign_binding_version")
    .executeTakeFirst();
  if (version?.value !== "2")
    throw new Error("campaign_binding_version_mismatch");
}

// Operator-only, after collection creation and before admitting mutations.
// Repeated installation verifies existing guards; it never repairs drift or
// silently rewrites pre-existing content/revision bindings.
export async function installCampaignBindings(database) {
  await requireCmsDatabase(database);
  await database.transaction().execute(async (transaction) => {
    await sql`SET LOCAL lock_timeout = '3s'`.execute(transaction);
    await sql`SET LOCAL statement_timeout = '5s'`.execute(transaction);
    await sql`SELECT pg_advisory_xact_lock(724381902)`.execute(transaction);
    await sql`LOCK TABLE public.ec_campaign_pages, public.revisions IN ACCESS EXCLUSIVE MODE`.execute(
      transaction,
    );
    const version = await transaction
      .selectFrom("options")
      .select("value")
      .where("name", "=", "leonaid:campaign_binding_version")
      .executeTakeFirst();
    if (version) {
      await requireCampaignBindings(transaction);
      return;
    }
    const invalid = await sql`
      SELECT 1 FROM public.ec_campaign_pages WHERE action_id IS NULL OR action_id !~ ${uuid}
      UNION ALL
      SELECT 1 FROM public.revisions r LEFT JOIN public.ec_campaign_pages c ON c.id=r.entry_id
      WHERE r.collection='campaign_pages' AND (c.id IS NULL OR (r.data::jsonb ->> 'action_id') IS DISTINCT FROM c.action_id)
      LIMIT 1
    `.execute(transaction);
    if (invalid.rows.length)
      throw new Error("campaign_binding_existing_data_invalid");
    const duplicates = await sql`
      SELECT 1 FROM public.ec_campaign_pages GROUP BY action_id HAVING count(*) > 1 LIMIT 1
    `.execute(transaction);
    if (duplicates.rows.length)
      throw new Error("campaign_binding_existing_duplicates");
    for (const guard of guards) {
      const existing =
        await sql`SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname=${guard.name}`.execute(
          transaction,
        );
      if (!existing.rows.length) {
        // Every interpolated byte below is a private source constant, not input.
        await sql
          .raw(
            `CREATE FUNCTION public.${guard.name}() RETURNS trigger
          LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $guard$${guard.body}$guard$`,
          )
          .execute(transaction);
        await sql
          .raw(
            `CREATE TRIGGER ${guard.name} BEFORE INSERT OR UPDATE ON public.${guard.table}
          FOR EACH ROW EXECUTE FUNCTION public.${guard.name}()`,
          )
          .execute(transaction);
      }
    }
    await sql`ALTER TABLE public.ec_campaign_pages
      ADD CONSTRAINT leonaid_campaign_action_unique UNIQUE (action_id)`.execute(
      transaction,
    );
    await transaction
      .insertInto("options")
      .values({
        name: "leonaid:campaign_binding_version",
        value: "2",
      })
      .execute();
    await requireCampaignBindings(transaction);
  });
}

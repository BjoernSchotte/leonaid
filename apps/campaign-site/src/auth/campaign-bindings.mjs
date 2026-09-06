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
    const invalid = await sql`
      SELECT 1 FROM public.ec_campaign_pages WHERE action_id IS NULL OR action_id !~ ${uuid}
      UNION ALL
      SELECT 1 FROM public.revisions r LEFT JOIN public.ec_campaign_pages c ON c.id=r.entry_id
      WHERE r.collection='campaign_pages' AND (c.id IS NULL OR (r.data::jsonb ->> 'action_id') IS DISTINCT FROM c.action_id)
      LIMIT 1
    `.execute(transaction);
    if (invalid.rows.length)
      throw new Error("campaign_binding_existing_data_invalid");
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
    await requireCampaignBindings(transaction);
  });
}

import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { createStorage } from "emdash/storage/s3";
import { installCampaignMedia } from "../../apps/campaign-site/src/auth/campaign-media.mjs";
const database = new Kysely({
  dialect: createDialect({
    host: "core-postgres",
    database: "emdash",
    user: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
try {
  switch (process.argv[2]) {
    case "install":
      await installCampaignMedia(database);
      break;
    case "fail-confirm":
      await sql`CREATE FUNCTION public.synthetic_confirm_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_confirm_failure'; END; $$`.execute(
        database,
      );
      await sql`CREATE TRIGGER synthetic_confirm_fail BEFORE UPDATE ON public.media FOR EACH ROW WHEN (OLD.filename='synthetic-confirm-failure.png' AND NEW.status='ready') EXECUTE FUNCTION public.synthetic_confirm_fail()`.execute(
        database,
      );
      break;
    case "restore-confirm":
      await sql`DROP TRIGGER synthetic_confirm_fail ON public.media`.execute(
        database,
      );
      await sql`DROP FUNCTION public.synthetic_confirm_fail()`.execute(
        database,
      );
      break;
    case "tamper": {
      const items = await database
        .selectFrom("media")
        .select("storage_key")
        .where("filename", "=", "synthetic-tamper.png")
        .execute();
      if (items.length !== 1) throw new Error("synthetic_media_target_invalid");
      await createStorage({}).upload({
        key: items[0].storage_key,
        contentType: "image/png",
        body: Buffer.from("synthetic-corruption"),
      });
      break;
    }
    default:
      throw new Error("synthetic_media_operation_invalid");
  }
  console.log(
    "media-runtime-operator: requested isolated fixture operation completed",
  );
} finally {
  await database.destroy();
}

import { isDeepStrictEqual } from "node:util";
import { sql } from "kysely";
import { SchemaRegistry } from "emdash";
import { applySeed } from "emdash/seed";
import {
  campaignCollection,
  campaignSchemaVersion,
} from "./campaign-schema.mjs";

const fieldContract = (field) => ({
  slug: field.slug,
  label: field.label,
  type: field.type,
  required: Boolean(field.required),
  unique: Boolean(field.unique),
  searchable: Boolean(field.searchable),
  indexed: Boolean(field.indexed),
  defaultValue: field.defaultValue ?? null,
  validation: field.validation ?? null,
  widget: field.widget ?? null,
  options: field.options ?? null,
});
const sortedFields = (fields) =>
  fields.map(fieldContract).sort((a, b) => a.slug.localeCompare(b.slug));

// Operator-only installation: no automatic repairs or content import. Existing
// schemas must match exactly; incompatible upgrades need an explicit migration.
export async function installCampaignSchema(database) {
  return database.transaction().execute(async (transaction) => {
    await sql`SET LOCAL lock_timeout = '3s'`.execute(transaction);
    await sql`SET LOCAL statement_timeout = '5s'`.execute(transaction);
    await sql`SELECT pg_advisory_xact_lock(724381904)`.execute(transaction);
    const version = await transaction
      .selectFrom("options")
      .select("value")
      .where("name", "=", "leonaid:campaign_schema_version")
      .executeTakeFirst();
    if (version && version.value !== JSON.stringify(campaignSchemaVersion))
      throw new Error("campaign_schema_version_mismatch");
    const registry = new SchemaRegistry(transaction);
    const existing = await registry.getCollection(campaignCollection.slug);
    if (!existing) {
      if (version) throw new Error("campaign_schema_missing");
      await applySeed(
        transaction,
        { version: "1", collections: [campaignCollection] },
        { includeContent: false, onConflict: "error" },
      );
    }
    const actual = await registry.getCollectionWithFields(
      campaignCollection.slug,
    );
    if (
      !actual ||
      actual.label !== campaignCollection.label ||
      actual.titleField !== campaignCollection.titleField ||
      actual.hasSeo ||
      actual.commentsEnabled ||
      !isDeepStrictEqual(
        [...actual.supports].sort(),
        [...campaignCollection.supports].sort(),
      ) ||
      !isDeepStrictEqual(
        sortedFields(actual.fields),
        sortedFields(campaignCollection.fields),
      )
    )
      throw new Error("campaign_schema_drift");
    if (!version)
      await transaction
        .insertInto("options")
        .values({
          name: "leonaid:campaign_schema_version",
          value: JSON.stringify(campaignSchemaVersion),
        })
        .execute();
    return { schemaVersion: campaignSchemaVersion, created: !existing };
  });
}

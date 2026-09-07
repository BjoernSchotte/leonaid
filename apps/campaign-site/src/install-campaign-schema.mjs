import { isDeepStrictEqual } from "node:util";
import { sql } from "kysely";
import { SchemaRegistry } from "emdash";
import { applySeed } from "emdash/seed";
import {
  campaignCollection,
  campaignCollectionV1,
  campaignCollectionV2,
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

async function assertSchema(registry, expected) {
  const actual = await registry.getCollectionWithFields(expected.slug);
  if (
    !actual ||
    actual.label !== expected.label ||
    actual.titleField !== expected.titleField ||
    actual.hasSeo ||
    actual.commentsEnabled ||
    !isDeepStrictEqual(
      [...actual.supports].sort(),
      [...expected.supports].sort(),
    ) ||
    !isDeepStrictEqual(
      sortedFields(actual.fields),
      sortedFields(expected.fields),
    )
  )
    throw new Error("campaign_schema_drift");
}

// Operator-only installation: no automatic repairs or content import. Existing
// schemas must match exactly; incompatible upgrades need an explicit migration.
export async function installCampaignSchema(
  database,
  { upgradeFromVersion1 = false, upgradeFromVersion2 = false } = {},
) {
  if (upgradeFromVersion1 && upgradeFromVersion2)
    throw new Error("campaign_schema_upgrade_ambiguous");
  return database.transaction().execute(async (transaction) => {
    await sql`SET LOCAL lock_timeout = '3s'`.execute(transaction);
    await sql`SET LOCAL statement_timeout = '5s'`.execute(transaction);
    await sql`SELECT pg_advisory_xact_lock(724381904)`.execute(transaction);
    const version = await transaction
      .selectFrom("options")
      .select("value")
      .where("name", "=", "leonaid:campaign_schema_version")
      .executeTakeFirst();
    const previousCollection =
      version?.value === "1" && upgradeFromVersion1
        ? campaignCollectionV1
        : version?.value === "2" && upgradeFromVersion2
          ? campaignCollectionV2
          : null;
    const upgrade = Boolean(previousCollection);
    if (
      version &&
      version.value !== JSON.stringify(campaignSchemaVersion) &&
      !upgrade
    )
      throw new Error("campaign_schema_version_mismatch");
    const registry = new SchemaRegistry(transaction);
    const existing = await registry.getCollection(campaignCollection.slug);
    if (upgrade) {
      await assertSchema(registry, previousCollection);
      for (const field of campaignCollection.fields) {
        const previous = previousCollection.fields.find(
          (item) => item.slug === field.slug,
        );
        if (!previous)
          await registry.createField(campaignCollection.slug, field);
        else if (
          !isDeepStrictEqual(fieldContract(previous), fieldContract(field))
        )
          await registry.updateField(campaignCollection.slug, field.slug, {
            validation: field.validation,
          });
      }
      await transaction
        .updateTable("options")
        .set({ value: JSON.stringify(campaignSchemaVersion) })
        .where("name", "=", "leonaid:campaign_schema_version")
        .execute();
    }
    if (!existing) {
      if (version) throw new Error("campaign_schema_missing");
      await applySeed(
        transaction,
        { version: "1", collections: [campaignCollection] },
        { includeContent: false, onConflict: "error" },
      );
    }
    await assertSchema(registry, campaignCollection);
    if (!version)
      await transaction
        .insertInto("options")
        .values({
          name: "leonaid:campaign_schema_version",
          value: JSON.stringify(campaignSchemaVersion),
        })
        .execute();
    return {
      schemaVersion: campaignSchemaVersion,
      created: !existing,
      upgraded: upgrade,
    };
  });
}

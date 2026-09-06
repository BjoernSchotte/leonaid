import { createHash } from "node:crypto";
import { campaignCollection } from "../campaign-schema.mjs";

// The Charity editor needs field metadata, not the global database manifest.
// Source-controlled data only: no settings, media keys, plugins, other schemas,
// taxonomy names or a hash that changes with another collection's metadata.
export function campaignManifest() {
  const fields = Object.fromEntries(
    campaignCollection.fields.map((field) => [
      field.slug,
      {
        kind: field.type === "text" ? "richText" : field.type,
        label: field.label,
        required: Boolean(field.required),
        ...(["repeater", "image"].includes(field.type)
          ? { validation: field.validation }
          : {}),
        ...(field.type === "select"
          ? {
              options: field.validation.options.map((value) => ({
                value,
                label: value,
              })),
            }
          : {}),
      },
    ]),
  );
  return {
    version: "0.36.0",
    hash: createHash("sha256")
      .update(JSON.stringify(campaignCollection))
      .digest("hex"),
    collections: {
      campaign_pages: {
        label: campaignCollection.label,
        labelSingular: "Campaign page",
        titleField: campaignCollection.titleField,
        supports: campaignCollection.supports,
        hasSeo: false,
        routable: true,
        fields,
      },
    },
    plugins: {},
    taxonomies: [],
    authMode: "leonaid-core",
    signupEnabled: false,
    contentLocale: { defaultLocale: "en", implicit: true },
    admin: { siteName: "LeonAid", favicon: "/favicon.svg" },
  };
}

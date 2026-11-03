import { createHash } from "node:crypto";
import { campaignCollection } from "../campaign-schema.mjs";

// Built-in EmDash areas that campaign editors never use. Their pages and APIs
// stay closed (default deny); hiding them keeps the sidebar to campaign pages.
// The same list is set in astro.config.mjs for the full manifest.
export const hiddenAdminNavItems = Object.freeze([
  "calendar",
  "media",
  "comments",
  "menus",
  "redirects",
  "widgets",
  "sections",
  "bylines",
  "import",
]);

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
    version: "1.4.0",
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
    admin: {
      siteName: "LeonAid",
      footerLabel: "LeonAid",
      favicon: "/favicon.svg",
      hiddenNavItems: [...hiddenAdminNavItems],
    },
  };
}

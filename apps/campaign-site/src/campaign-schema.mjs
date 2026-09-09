// Versioned editorial schema. Core remains authoritative for all business data.
export const campaignSchemaVersion = 3;
// Retained verbatim for strict, explicit version-1 migration preflight.
export const campaignCollectionV1 = {
  slug: "campaign_pages",
  label: "Campaign pages",
  titleField: "title",
  supports: ["drafts", "revisions"],
  fields: [
    {
      slug: "action_id",
      label: "Core action",
      type: "string",
      required: true,
      indexed: true,
    },
    {
      slug: "title",
      label: "Title",
      type: "text",
      searchable: true,
      validation: { minLength: 1, maxLength: 400 },
    },
    {
      slug: "hero_title",
      label: "Hero heading",
      type: "string",
      validation: { maxLength: 180 },
    },
    {
      slug: "hero_summary",
      label: "Hero introduction",
      type: "text",
      validation: { maxLength: 1200 },
    },
    { slug: "body", label: "Campaign story", type: "portableText" },
    {
      slug: "faq",
      label: "Frequently asked questions",
      type: "repeater",
      validation: {
        maxItems: 20,
        subFields: [
          {
            slug: "question",
            label: "Question",
            type: "string",
            required: true,
          },
          { slug: "answer", label: "Answer", type: "text", required: true },
        ],
      },
    },
    {
      slug: "partners",
      label: "Partners",
      type: "repeater",
      validation: {
        maxItems: 30,
        subFields: [
          { slug: "name", label: "Name", type: "string", required: true },
          { slug: "description", label: "Description", type: "text" },
          { slug: "website", label: "Website", type: "url" },
        ],
      },
    },
    {
      slug: "theme",
      label: "Theme",
      type: "select",
      validation: { options: ["leonaid", "krapfentaxi"] },
    },
    {
      slug: "seo_description",
      label: "Search description",
      type: "text",
      validation: { maxLength: 320 },
    },
  ],
};

const imageField = (slug, label) => ({
  slug,
  label,
  type: "image",
  validation: { allowedMimeTypes: ["image/png", "image/jpeg", "image/webp"] },
});
export const campaignCollectionV2 = {
  ...campaignCollectionV1,
  fields: [
    ...campaignCollectionV1.fields.map((field) =>
      field.slug === "partners"
        ? {
            ...field,
            validation: {
              ...field.validation,
              subFields: [
                ...field.validation.subFields,
                imageField("logo", "Partner logo"),
              ],
            },
          }
        : field,
    ),
    imageField("hero_image", "Hero image"),
    imageField("social_image", "Social sharing image"),
  ],
};

// Editorial branding stays campaign-owned; no business facts are copied here.
export const campaignCollection = {
  ...campaignCollectionV2,
  fields: [
    ...campaignCollectionV2.fields.map((field) =>
      field.slug === "partners"
        ? {
            ...field,
            validation: {
              ...field.validation,
              subFields: [
                ...field.validation.subFields,
                {
                  slug: "eyebrow",
                  label: "Section label",
                  type: "string",
                  validation: { maxLength: 180 },
                },
                {
                  slug: "link_label",
                  label: "Link label",
                  type: "string",
                  validation: { maxLength: 120 },
                },
              ],
            },
          }
        : field,
    ),
    imageField("brand_logo", "Campaign logo"),
    {
      slug: "story_eyebrow",
      label: "Story section label",
      type: "string",
      validation: { maxLength: 180 },
    },
    {
      slug: "story_title",
      label: "Story heading",
      type: "text",
      validation: { maxLength: 180 },
    },
  ],
};

export function exportCampaignSchema() {
  return (
    JSON.stringify(
      {
        schema_version: campaignSchemaVersion,
        seed: { version: "1", collections: [campaignCollection] },
      },
      null,
      2,
    ) + "\n"
  );
}

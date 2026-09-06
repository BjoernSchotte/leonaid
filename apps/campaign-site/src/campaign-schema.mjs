// Versioned editorial schema. Core remains authoritative for all business data.
// Media fields are added only with the campaign-scoped storage/preview proof.
export const campaignSchemaVersion = 1;
export const campaignCollection = {
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

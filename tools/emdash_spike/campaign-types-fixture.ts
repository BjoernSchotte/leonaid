import type {
  CampaignPageFields,
  CampaignSchemaVersion,
} from "../../apps/campaign-site/src/campaign-fields.generated.js";

const version: CampaignSchemaVersion = 3;
const minimal: CampaignPageFields = { action_id: "synthetic-core-id" };
const page: CampaignPageFields = {
  action_id: minimal.action_id,
  title: "Synthetic campaign",
  hero_title: null,
  hero_summary: "Introduction",
  body: [],
  faq: [{ _key: "faq1", question: "When?", answer: "Soon." }],
  partners: [{ name: "Synthetic partner", description: null, website: null }],
  theme: "krapfentaxi",
  seo_description: null,
  hero_image: {
    id: "synthetic-media-id",
    provider: "local",
    alt: "Synthetic hero",
  },
  social_image: null,
};
const nullable: CampaignPageFields = {
  action_id: page.action_id,
  title: null,
  hero_title: null,
  hero_summary: null,
  body: null,
  faq: null,
  partners: null,
  theme: null,
  seo_description: null,
};

// These checks must keep producing compiler errors, not merely compile via any.
// @ts-expect-error action_id is required
const missingAction: CampaignPageFields = {};
// @ts-expect-error action_id is not nullable
const nullAction: CampaignPageFields = { action_id: null };
// @ts-expect-error theme is a closed schema-derived union
page.theme = "arbitrary-theme";
// @ts-expect-error FAQ answers are required
page.faq = [{ question: "Missing answer" }];
// @ts-expect-error partner names are strings
page.partners = [{ name: 42 }];
// @ts-expect-error hero heading is text, not executable structured content
page.hero_title = { html: "<script>" };
// @ts-expect-error business data is not a CMS field
page.order_total = 100;
// @ts-expect-error only local image providers are supported
page.social_image = { id: "unscoped-media", provider: "external" };
page.hero_image = {
  id: "synthetic-media",
  // @ts-expect-error arbitrary cached storage metadata is not supported
  meta: { url: "https://example.invalid" },
};
// @ts-expect-error schema version is literal
const wrongVersion: CampaignSchemaVersion = 1;
void [version, nullable, missingAction, nullAction, wrongVersion];

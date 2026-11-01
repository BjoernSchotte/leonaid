import type { AstroComponentFactory } from "astro/runtime/server/index.js";

import {
  hasPublicTheme,
  resolvePublicTheme,
  type PublicTheme,
} from "../../../public/src/themes";
import type { CampaignPageFields } from "../campaign-fields.generated";
import KrapfentaxiCampaignIntro from "../components/KrapfentaxiCampaignIntro.astro";

// The CMS theme options are part of the versioned CMS schema
// (campaign-schema.mjs). This Record is exhaustive over the generated union,
// so a new CMS option fails type checking until it is registered here.
type CampaignThemeKey = NonNullable<CampaignPageFields["theme"]>;

export interface CampaignTheme {
  /** Layout theme shared with Core-rendered pages (apps/public). */
  readonly publicTheme: PublicTheme;
  /** CMS-driven intro; without one the generic editorial story is shown. */
  readonly Intro?: AstroComponentFactory;
}

const campaignThemes: Readonly<Record<CampaignThemeKey, CampaignTheme>> = {
  leonaid: { publicTheme: resolvePublicTheme("leonaid") },
  krapfentaxi: {
    publicTheme: resolvePublicTheme("krapfentaxi"),
    Intro: KrapfentaxiCampaignIntro,
  },
};

for (const key of Object.keys(campaignThemes)) {
  if (!hasPublicTheme(key)) {
    throw new Error(`CMS theme ${key} has no registered public theme`);
  }
}

/** Resolve the editor-selected theme; no selection keeps the neutral look. */
export function resolveCampaignTheme(
  key: CampaignPageFields["theme"],
): CampaignTheme {
  return key ? campaignThemes[key] : campaignThemes.leonaid;
}

import { defineCollection } from "astro:content";
import { z } from "astro/zod";
import { docsLoader, i18nLoader } from "@astrojs/starlight/loaders";
import { docsSchema, i18nSchema } from "@astrojs/starlight/schema";

const audience = z.enum(["user", "ops", "dev"]);

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        description: z.string().min(20),
        docId: z.string().regex(/^DOC-P\d{3}$/),
        audience: z.array(audience).min(1),
        diataxis: z.enum(["tutorial", "how-to", "reference", "explanation"]),
        contentRevision: z.number().int().positive(),
        reviewedRevision: z.number().int().positive(),
        verifiedAgainst: z.string().regex(/^[0-9a-f]{40}$/),
        reviewer: z.string().min(2),
      }),
    }),
  }),
  i18n: defineCollection({ loader: i18nLoader(), schema: i18nSchema() }),
};

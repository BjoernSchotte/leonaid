import { z } from "astro/zod";

const key = z.string().regex(/^[A-Za-z0-9_-]{1,100}$/);
const text = (max) => z.string().max(max);
const storageKey = z
  .string()
  .regex(
    /^campaigns\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpg|webp)$/,
  );
// Native image shape, deliberately local-only. Database ownership and every
// optional cached fact are checked separately before any upstream mutation.
export const campaignImageReference = z
  .object({
    id: z.string().regex(/^[0-9A-HJKMNP-TV-Z]{26}$/),
    provider: z.literal("local").optional(),
    alt: text(400).optional(),
    width: z.number().int().min(1).max(8192).optional(),
    height: z.number().int().min(1).max(8192).optional(),
    filename: text(200).optional(),
    mimeType: z.enum(["image/png", "image/jpeg", "image/webp"]).optional(),
    // The native provider enriches these nullable cached facts on save. Their
    // values must match the media row, never caller-supplied arbitrary metadata.
    meta: z
      .object({
        storageKey,
        caption: text(4000).nullish(),
        blurhash: text(200).nullish(),
        dominantColor: z
          .string()
          .regex(/^#[0-9a-fA-F]{6}$/)
          .nullish(),
      })
      .strict()
      .optional(),
  })
  .strict();
const href = text(2048).refine((value) => {
  if (/[\u0000-\u0020\u007f\\]/.test(value)) return false;
  if (value.startsWith("/") && !value.startsWith("//")) return true;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
});
const block = z
  .object({
    _type: z.literal("block"),
    _key: key,
    style: z.enum(["normal", "h2", "h3", "blockquote"]).optional(),
    listItem: z.enum(["bullet", "number"]).optional(),
    level: z.number().int().min(1).max(3).optional(),
    markDefs: z
      .array(z.object({ _type: z.literal("link"), _key: key, href }).strict())
      .max(30)
      .optional(),
    children: z
      .array(
        z
          .object({
            _type: z.literal("span"),
            _key: key,
            text: text(4000),
            marks: z.array(key).max(8).optional(),
          })
          .strict(),
      )
      .max(100),
  })
  .strict()
  .refine((value) => {
    // Native EmDash omits empty arrays. Absence means no annotations, never
    // permission to accept unregistered marks or relax the bounded schema.
    const definitions = (value.markDefs ?? []).map((mark) => mark._key);
    const keys = value.children.map((child) => child._key);
    const marks = new Set([
      "strong",
      "em",
      "underline",
      "strike-through",
      "code",
      ...definitions,
    ]);
    return (
      new Set(definitions).size === definitions.length &&
      new Set(keys).size === keys.length &&
      value.children.every((child) =>
        (child.marks ?? []).every((mark) => marks.has(mark)),
      )
    );
  });

// Validate without silently stripping unknown keys. Plain strings remain text,
// not markup; executable blocks, custom annotations and arbitrary URLs are denied.
export const campaignEditorial = z
  .object({
    title: text(400).refine((value) => Boolean(value.trim())),
    action_id: z.uuid().optional(),
    hero_title: text(180).nullish(),
    hero_summary: text(1200).nullish(),
    hero_image: campaignImageReference.nullish(),
    social_image: campaignImageReference.nullish(),
    body: z
      .array(block)
      .max(60)
      .refine(
        (blocks) =>
          new Set(blocks.map((item) => item._key)).size === blocks.length,
      )
      .nullish(),
    faq: z
      .array(
        z
          .object({
            _key: key.optional(),
            question: text(300).min(1),
            answer: text(2400).min(1),
          })
          .strict(),
      )
      .max(20)
      .nullish(),
    partners: z
      .array(
        z
          .object({
            _key: key.optional(),
            name: text(200).min(1),
            description: text(800).nullish(),
            website: href.or(z.literal("")).nullish(),
            logo: campaignImageReference.nullish(),
          })
          .strict(),
      )
      .max(30)
      .nullish(),
    theme: z.enum(["leonaid", "krapfentaxi"]).nullish(),
    seo_description: text(320).nullish(),
  })
  .strict();

export function validCampaignEditorial(data) {
  // Bound both nested content and the aggregate, including escaped JSON bytes.
  try {
    return (
      Buffer.byteLength(JSON.stringify(data), "utf8") <= 60 * 1024 &&
      campaignEditorial.safeParse(data).success
    );
  } catch {
    return false;
  }
}

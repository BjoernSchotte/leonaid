import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { campaignEditorial } from "../../apps/campaign-site/src/auth/campaign-editorial.mjs";

export const krapfentaxiImportVersion = 1;
const root = new URL("../../", import.meta.url);
const assetDirectory = "apps/public/src/assets/krapfentaxi/";
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const textSources = [
  {
    path: "apps/public/src/components/KrapfentaxiIntro.astro",
    sha256: "02de70e6836a63b0d970bee7db7e6b3092747e39200a850a1d43429898d58e91",
  },
  {
    path: `${assetDirectory}SOURCES.md`,
    sha256: "53a1ffa7de9f07951ab5485629590edb6ffa6bbf76bdc2acf5ab2b001bf9df47",
  },
];
const assetSources = [
  {
    key: "hero",
    filename: "hero.webp",
    mimeType: "image/webp",
    sha256: "b2846f8ab1f3a0836d081aaa9948e7ee3b868ed9aefd2e8d6c909302de26ea1c",
    source: "https://lions-krapfentaxi.de/img/home/bg.webp",
    alt: "Ein Löwe im Krapfentaxi vor der Würzburger Residenz.",
  },
  {
    key: "logo",
    filename: "logo.png",
    mimeType: "image/png",
    sha256: "0c2c752e1961a456a06cea1e1b0eafc1a99280203a05e1080f61c842170cd9fd",
    source: "https://lions-krapfentaxi.de/img/logos/home/logo_2.png",
    alt: "Lions Krapfentaxi",
  },
  {
    key: "partner",
    filename: "roesner.jpg",
    mimeType: "image/jpeg",
    sha256: "382e3841b85a0f7c6e3af9e04793ee5959018e1bcbb7e01349f33b519202f517",
    source:
      "https://lions-krapfentaxi.de/img/logos/sponsor/logo_roesner_20251124_152038.jpg",
    alt: "Rösner Backstube",
  },
];
const paragraph = (key, text) => ({
  _type: "block",
  _key: key,
  style: "normal",
  markDefs: [],
  children: [{ _type: "span", _key: `${key}-text`, marks: [], text }],
});

// Deliberate transcription of the pinned existing component, not generated
// marketing copy. Core-owned name/purpose/dates/prices/beneficiaries/legal text
// are intentionally absent. Title is an editorial label, not the action name.
function editorialCopy() {
  return {
    title: "Krapfentaxi-Microsite",
    theme: "krapfentaxi",
    hero_title: null,
    hero_summary: "Eine kleine Geste für dein Team. Eine große Hilfe vor Ort.",
    story_eyebrow: "Das Lions Krapfentaxi",
    story_title: "Freude teilen.\nGutes möglich machen.",
    body: [
      paragraph(
        "attention",
        "Für die Kolleginnen und Kollegen, Geschäftspartner oder einfach für Menschen, denen du eine Freude machen möchtest: Mit Krapfen wird aus einer kleinen Aufmerksamkeit gemeinsame Unterstützung.",
      ),
      paragraph(
        "together",
        "Die Lions bringen Menschen zusammen. Welche Einrichtungen diese Aktion unterstützt, erfährst du weiter unten.",
      ),
    ],
    partners: [
      {
        name: "Unsere Krapfenbäckerei:\nRösner Backstube.",
        eyebrow: "Aus der Region. Für die Region.",
        description:
          "Handwerk aus Würzburg: In der Rösner Backstube entstehen mit Hiffenmark gefüllte Krapfen. Regional gebacken, gemeinsam genossen – so verbinden sich süße Freude und ein guter Zweck.",
        website: "https://www.roesner-backstube.de/",
        link_label: "Zur Rösner Backstube",
      },
    ],
  };
}

async function readPinned(source, maximum) {
  const handle = await open(
    fileURLToPath(new URL(source.path, root)),
    constants.O_RDONLY | constants.O_NOFOLLOW,
  );
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size < 1 || info.size > maximum)
      throw new Error("krapfentaxi_source_invalid");
    const bytes = Buffer.alloc(info.size + 1);
    let size = 0;
    while (size < bytes.length) {
      const result = await handle.read(bytes, size, bytes.length - size, null);
      if (!result.bytesRead) break;
      size += result.bytesRead;
    }
    const content = bytes.subarray(0, size);
    if (size !== info.size || sha256(content) !== source.sha256)
      throw new Error("krapfentaxi_source_drift");
    return content;
  } finally {
    await handle.close();
  }
}

// Read-only and offline; URLs document provenance and are never fetched.
// No caller-selected paths, action IDs, secrets or mutable business snapshots
// enter the source package. Keep the rights notice in private import metadata.
export async function loadKrapfentaxiSource() {
  const texts = [];
  for (const source of textSources)
    texts.push(await readPinned(source, 64 * 1024));
  const editorial = editorialCopy();
  campaignEditorial.parse(editorial);
  const assets = [];
  for (const source of assetSources) {
    const path = `${assetDirectory}${source.filename}`;
    assets.push({
      ...source,
      path,
      bytes: await readPinned({ ...source, path }, 8 * 1024 * 1024),
    });
  }
  const manifest = {
    migration: "krapfentaxi-demo",
    version: krapfentaxiImportVersion,
    sources: textSources.map((source) => ({ ...source })),
    assets: assets.map(({ bytes, ...source }) => ({
      ...source,
      size: bytes.length,
    })),
    rightsNotice: texts[1].toString("utf8"),
    productionRightsCleared: false,
    editorial,
  };
  return { manifest, fingerprint: sha256(JSON.stringify(manifest)), assets };
}

// Only after each imported media item has a verified ready/action binding may
// the coordinator produce the native CMS payload. These references intentionally
// exclude raw storage keys and original file metadata. No publication occurs.
export function krapfentaxiImportData(actionId, media) {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      actionId,
    )
  )
    throw new Error("krapfentaxi_action_invalid");
  const reference = (key) => {
    const item = media?.[key];
    if (
      !item ||
      item.status !== "ready" ||
      item.actionId !== actionId ||
      !/^[0-9A-HJKMNP-TV-Z]{26}$/.test(item.id) ||
      !Number.isSafeInteger(item.width) ||
      item.width < 1 ||
      item.width > 8192 ||
      !Number.isSafeInteger(item.height) ||
      item.height < 1 ||
      item.height > 8192
    )
      throw new Error("krapfentaxi_media_invalid");
    return {
      id: item.id,
      provider: "local",
      width: item.width,
      height: item.height,
      alt: assetSources.find((source) => source.key === key).alt,
    };
  };
  const data = editorialCopy();
  return campaignEditorial.parse({
    ...data,
    action_id: actionId,
    hero_image: reference("hero"),
    social_image: reference("hero"),
    brand_logo: reference("logo"),
    partners: [{ ...data.partners[0], logo: reference("partner") }],
  });
}

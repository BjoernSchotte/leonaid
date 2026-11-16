import sharp from "sharp";
import { createHash } from "node:crypto";
import { campaignStorage } from "../auth/campaign-media-io.mjs";

const imageTypes = ["image/png", "image/jpeg", "image/webp"];
// Rendered widths, keyed by content hash and width. The hash pins the bytes,
// so an entry never goes stale; it only ages out. Originals are not kept: each
// is read and verified against its hash again, so a damaged or missing object
// is refused at once. Browsers keep versioned originals themselves (E-067).
const budgetBytes = 48 * 1024 * 1024;
const files = new Map();
let usedBytes = 0;
const pending = new Map();
// One resize at a time per process; the rest wait their turn.
let resizing = Promise.resolve();

function remember(key, file) {
  if (files.has(key) || file.bytes.length > budgetBytes / 4) return;
  files.set(key, file);
  usedBytes += file.bytes.length;
  while (usedBytes > budgetBytes) {
    const [oldest, entry] = files.entries().next().value;
    files.delete(oldest);
    usedBytes -= entry.bytes.length;
  }
}

function recall(key) {
  const file = files.get(key);
  if (!file) return null;
  // Refresh its place: the least recently served entry leaves first.
  files.delete(key);
  files.set(key, file);
  return file;
}

async function original(media) {
  const stored = await campaignStorage().download(media.storage_key);
  if (
    !imageTypes.includes(media.mime_type) ||
    !/^[0-9a-f]{64}$/.test(media.content_hash ?? "") ||
    stored.contentType !== media.mime_type ||
    createHash("sha256").update(stored.bytes).digest("hex") !==
      media.content_hash
  )
    throw new Error("public_media_integrity");
  return { bytes: Buffer.from(stored.bytes), contentType: media.mime_type };
}

function scaled(source, width) {
  const job = resizing.then(async () => {
    const bytes = await sharp(source.bytes, {
      failOn: "warning",
      limitInputPixels: 16_000_000,
    })
      .resize({ width, withoutEnlargement: true })
      .webp({ quality: 80 })
      .timeout({ seconds: 10 })
      .toBuffer();
    return { bytes, contentType: "image/webp" };
  });
  resizing = job.catch(() => undefined);
  return job;
}

// The verified bytes of a published file, or one of its rendered widths.
// Callers must have authorised the request; this only reads and verifies.
export async function publicMediaBytes(media, width) {
  if (width === null || width >= media.width) return original(media);
  const key = `${media.content_hash}:${width}`;
  const cached = recall(key);
  if (cached) return cached;
  let job = pending.get(key);
  if (!job) {
    job = original(media)
      .then((source) => scaled(source, width))
      .finally(() => pending.delete(key));
    pending.set(key, job);
  }
  const file = await job;
  remember(key, file);
  return file;
}

export function forgetPublicMediaBytes() {
  files.clear();
  pending.clear();
  usedBytes = 0;
}

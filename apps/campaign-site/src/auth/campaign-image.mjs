import sharp from "sharp";
import { createHash } from "node:crypto";

export const campaignImageMaxBytes = 8 * 1024 * 1024;
export const campaignImageMaxPixels = 16_000_000;
const formats = {
  "image/png": "png",
  "image/jpeg": "jpeg",
  "image/webp": "webp",
};
let processing = false;

function matchesSignature(bytes, mime) {
  if (mime === "image/png")
    return bytes
      .subarray(0, 8)
      .equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  if (mime === "image/jpeg")
    return bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
  if (mime === "image/webp")
    return (
      bytes.subarray(0, 4).toString("ascii") === "RIFF" &&
      bytes.subarray(8, 12).toString("ascii") === "WEBP"
    );
  return false;
}

// Only bounded raster bytes enter libvips. Never pass URLs, filesystem paths,
// client dimensions, SVG/XML or other auto-detected formats to the decoder.
// Re-encoding drops EXIF/GPS, comments and appended content. Originals are not
// retained in storage. One decode per process; overload is rejected, not queued.
export async function normalizeCampaignImage(input, mimeType) {
  if (
    !(input instanceof Uint8Array) ||
    input.byteLength < 1 ||
    input.byteLength > campaignImageMaxBytes ||
    !formats[mimeType]
  )
    throw new Error("campaign_image_invalid");
  const bytes = Buffer.from(input);
  if (!matchesSignature(bytes, mimeType))
    throw new Error("campaign_image_invalid");
  if (processing) throw new Error("campaign_image_busy");
  processing = true;
  let decoder;
  try {
    decoder = sharp(bytes, {
      failOn: "warning",
      limitInputPixels: campaignImageMaxPixels,
      animated: true,
    });
    const metadata = await decoder.metadata();
    if (
      metadata.format !== formats[mimeType] ||
      (metadata.pages ?? 1) !== 1 ||
      !Number.isSafeInteger(metadata.width) ||
      !Number.isSafeInteger(metadata.height) ||
      metadata.width < 1 ||
      metadata.height < 1 ||
      metadata.width > 8192 ||
      metadata.height > 8192 ||
      metadata.width * metadata.height > campaignImageMaxPixels
    )
      throw new Error("campaign_image_invalid");
    const { data, info } = await decoder
      .rotate()
      .toFormat(formats[mimeType])
      .timeout({ seconds: 5 })
      .toBuffer({ resolveWithObject: true });
    if (
      data.length < 1 ||
      data.length > campaignImageMaxBytes ||
      info.format !== formats[mimeType] ||
      !matchesSignature(data, mimeType)
    )
      throw new Error("campaign_image_invalid");
    return {
      bytes: data,
      mimeType,
      size: data.length,
      width: info.width,
      height: info.height,
      contentHash: createHash("sha256").update(data).digest("hex"),
    };
  } catch {
    // Decoder failures can carry private input details. Do not retain causes.
    throw new Error("campaign_image_invalid");
  } finally {
    decoder?.destroy();
    processing = false;
  }
}

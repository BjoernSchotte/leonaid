import {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
  DeleteObjectCommand,
} from "@aws-sdk/client-s3";
import { campaignImageMaxBytes } from "./campaign-image.mjs";

export class CampaignMediaError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
  }
}

// Consume the actual body, not an unbounded clone/tee. A declared length never
// substitutes for counting bytes. Cancel stalled streams without awaiting them.
export async function readCampaignBytes(body, maximum, timeoutMs = 5000) {
  if (!body) throw new CampaignMediaError(400, "MEDIA_BODY_INVALID");
  const reader = body.getReader();
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new CampaignMediaError(408, "MEDIA_BODY_TIMEOUT")),
      timeoutMs,
    );
  });
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await Promise.race([reader.read(), deadline]);
      if (done) break;
      size += value.byteLength;
      if (size > maximum)
        throw new CampaignMediaError(413, "MEDIA_BODY_TOO_LARGE");
      chunks.push(value);
    }
    return Buffer.concat(chunks);
  } finally {
    clearTimeout(timer);
    void reader.cancel().catch(() => {});
  }
}

let storage;
// Same private bucket and scoped runtime credentials as EmDash, but with
// explicit transport budgets. No presigned browser URL or public bucket policy.
export function campaignStorage() {
  if (storage) return storage;
  if (
    process.env.S3_ENDPOINT !== "http://rustfs:9000" ||
    process.env.S3_BUCKET !== "emdash-media" ||
    process.env.S3_ACCESS_KEY_ID !== "leonaid-emdash" ||
    !process.env.S3_SECRET_ACCESS_KEY
  )
    throw new CampaignMediaError(503, "MEDIA_STORAGE_UNAVAILABLE");
  const client = new S3Client({
    endpoint: "http://rustfs:9000",
    region: "us-east-1",
    forcePathStyle: true,
    maxAttempts: 1,
    credentials: {
      accessKeyId: process.env.S3_ACCESS_KEY_ID,
      secretAccessKey: process.env.S3_SECRET_ACCESS_KEY,
    },
    requestHandler: { connectionTimeout: 2000, requestTimeout: 5000 },
  });
  const send = (command) =>
    client.send(command, { abortSignal: AbortSignal.timeout(8000) });
  storage = {
    async upload({ key, body, contentType }) {
      if (
        !(body instanceof Uint8Array) ||
        body.byteLength > campaignImageMaxBytes
      )
        throw new CampaignMediaError(413, "MEDIA_BODY_TOO_LARGE");
      await send(
        new PutObjectCommand({
          Bucket: "emdash-media",
          Key: key,
          Body: body,
          ContentType: contentType,
        }),
      );
      return { key, size: body.byteLength };
    },
    async download(key) {
      const object = await send(
        new GetObjectCommand({ Bucket: "emdash-media", Key: key }),
      );
      const bytes = await readCampaignBytes(
        object.Body?.transformToWebStream(),
        campaignImageMaxBytes,
      );
      if (bytes.length !== object.ContentLength)
        throw new CampaignMediaError(503, "MEDIA_STORAGE_UNAVAILABLE");
      return { bytes, contentType: object.ContentType, size: bytes.length };
    },
    async delete(key) {
      await send(new DeleteObjectCommand({ Bucket: "emdash-media", Key: key }));
    },
  };
  return storage;
}

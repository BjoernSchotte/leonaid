import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { createStorage } from "emdash/storage/s3";
import { MediaRepository } from "emdash";
import sharp from "sharp";
import {
  normalizeCampaignImage,
  campaignImageMaxBytes,
} from "../../apps/campaign-site/src/auth/campaign-image.mjs";
import {
  installCampaignMedia,
  requireCampaignMedia,
  createCampaignPendingMedia,
  getCampaignMedia,
  listCampaignMedia,
} from "../../apps/campaign-site/src/auth/campaign-media.mjs";
import { stageCampaignImageUpload } from "../../apps/campaign-site/src/auth/campaign-media-upload.mjs";

const a = "20000000-0000-4000-8000-000000000001";
const b = "20000000-0000-4000-8000-000000000002";
const actor = (actionId) => ({
  globalRoles: [],
  actionMemberships: [{ actionId, role: "charity_admin" }],
});
const authorId = "01K00000000000000000000001";
const database = new Kysely({
  dialect: createDialect({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password: process.env.PGPASSWORD,
  }),
});
const storage = createStorage({});
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const objectKeys = async () =>
  (await storage.list()).files.map((file) => file.key).sort();
const snapshot = async () => ({
  media: await database.selectFrom("media").selectAll().orderBy("id").execute(),
  bindings: await database
    .selectFrom("leonaid_campaign_media")
    .selectAll()
    .orderBy("media_id")
    .execute(),
  attempts: await database
    .selectFrom("_emdash_media_upload_attempts")
    .selectAll()
    .orderBy("storage_key")
    .execute(),
  keys: await objectKeys(),
});
async function verifyStored(item) {
  assert.equal(item.status, "pending");
  assert.match(item.contentHash, /^[0-9a-f]{64}$/);
  assert.equal(
    await new MediaRepository(database).hasUploadAttempt(item.storageKey),
    true,
  );
  const stored = await storage.download(item.storageKey);
  const bytes = Buffer.from(await new Response(stored.body).arrayBuffer());
  assert.equal(bytes.length, stored.size);
  assert.equal(hash(bytes), item.contentHash);
  assert.equal(stored.contentType, item.mimeType);
  const info = await sharp(bytes).metadata();
  assert.ok(!info.exif && !info.xmp && !info.icc);
  const anonymous = await fetch(
    `${process.env.S3_ENDPOINT}/${process.env.S3_BUCKET}/${item.storageKey}`,
    { signal: AbortSignal.timeout(5000) },
  );
  await anonymous.body?.cancel();
  assert.equal(anonymous.status, 403);
  return bytes;
}
try {
  if (process.argv.includes("--existing")) {
    await requireCampaignMedia(database);
    const entries = await database
      .selectFrom("leonaid_campaign_media")
      .select("media_id")
      .where("action_id", "=", a)
      .execute();
    let retained = 0;
    for (const { media_id: id } of entries) {
      const item = await getCampaignMedia(database, actor(a), a, id);
      if (!item.contentHash) continue;
      await verifyStored(item);
      retained++;
    }
    assert.equal(retained, 3);
    assert.deepEqual(
      (await listCampaignMedia(database, actor(a), a)).items,
      [],
    );
    console.log(
      "campaign-media-upload: OK: SQL bindings, staged hashes, actual private image bytes and pending state survive PostgreSQL/RustFS restart; anonymous S3 reads remain denied",
    );
  } else {
    await installCampaignMedia(database);
    const images = {};
    for (const [mime, format] of [
      ["image/png", "png"],
      ["image/jpeg", "jpeg"],
      ["image/webp", "webp"],
    ]) {
      images[mime] = await sharp({
        create: { width: 6, height: 4, channels: 3, background: "#a94060" },
      })
        .toFormat(format)
        .withMetadata({ orientation: 6 })
        .toBuffer();
      const normalized = await normalizeCampaignImage(images[mime], mime);
      assert.equal(normalized.mimeType, mime);
      assert.equal(normalized.contentHash, hash(normalized.bytes));
      const metadata = await sharp(normalized.bytes).metadata();
      assert.equal(normalized.width, metadata.width);
      assert.equal(normalized.height, metadata.height);
      assert.ok(!metadata.exif && !metadata.xmp && !metadata.icc);
      if (mime === "image/jpeg")
        assert.deepEqual([normalized.width, normalized.height], [4, 6]);
    }
    const png = images["image/png"];
    const appended = Buffer.concat([
      png,
      Buffer.from("<script>leonaid-synthetic-marker</script>"),
    ]);
    assert.equal(
      (await normalizeCampaignImage(appended, "image/png")).bytes.includes(
        Buffer.from("leonaid-synthetic-marker"),
      ),
      false,
    );
    const oversizedDimensions = await sharp({
      create: { width: 8193, height: 1, channels: 3, background: "red" },
    })
      .png()
      .toBuffer();
    const oversizedPixels = await sharp({
      create: { width: 4001, height: 4000, channels: 3, background: "red" },
    })
      .png()
      .toBuffer();
    const animated = await sharp(
      Buffer.concat([Buffer.alloc(2 * 2 * 3), Buffer.alloc(2 * 2 * 3, 255)]),
      {
        raw: { width: 2, height: 4, channels: 3, pageHeight: 2 },
      },
    )
      .webp({ loop: 0, delay: [100, 100] })
      .toBuffer();
    assert.equal(
      (await sharp(animated, { animated: true }).metadata()).pages,
      2,
    );
    for (const [bytes, mime] of [
      [
        Buffer.from(
          "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        ),
        "image/png",
      ],
      [Buffer.from("<html>not a raster</html>"), "image/jpeg"],
      [png, "image/svg+xml"],
      [png, "image/jpeg"],
      [png, "image/png; charset=utf-8"],
      [png.subarray(0, 40), "image/png"],
      [images["image/jpeg"].subarray(0, 30), "image/jpeg"],
      [Buffer.alloc(0), "image/png"],
      [Buffer.alloc(campaignImageMaxBytes + 1), "image/png"],
      [oversizedDimensions, "image/png"],
      [oversizedPixels, "image/png"],
      [animated, "image/webp"],
      ["/private/never-read.png", "image/png"],
    ])
      await assert.rejects(
        normalizeCampaignImage(bytes, mime),
        /campaign_image_invalid/,
      );
    const concurrent = await Promise.allSettled([
      normalizeCampaignImage(png, "image/png"),
      normalizeCampaignImage(png, "image/png"),
    ]);
    assert.equal(concurrent[0].status, "fulfilled");
    assert.equal(concurrent[1].status, "rejected");
    assert.equal(concurrent[1].reason.message, "campaign_image_busy");
    console.log(
      "campaign-image: OK: real PNG/JPEG/WebP decode and re-encode, EXIF orientation/privacy, appended-content stripping, malformed/MIME/size/pixel/dimension/animation denial and bounded decode admission",
    );

    for (const [mimeType, bytes] of Object.entries(images)) {
      const item = await createCampaignPendingMedia(database, actor(a), a, {
        filename: `synthetic-${mimeType.split("/")[1]}`,
        mimeType,
        size: bytes.length,
        authorId,
      });
      assert.deepEqual(
        await stageCampaignImageUpload(
          database,
          storage,
          actor(a),
          a,
          item.id,
          bytes,
          mimeType,
        ),
        { uploaded: true, size: bytes.length },
      );
      const staged = await getCampaignMedia(database, actor(a), a, item.id);
      assert.notEqual(staged.storageKey, item.storageKey);
      assert.equal(staged.size, bytes.length);
      const storedBytes = await verifyStored(staged);
      assert.deepEqual(
        storedBytes,
        (await normalizeCampaignImage(bytes, mimeType)).bytes,
      );
      const before = await snapshot();
      await assert.rejects(
        stageCampaignImageUpload(
          database,
          storage,
          actor(b),
          b,
          item.id,
          bytes,
          mimeType,
        ),
        /campaign_media_not_found/,
      );
      await assert.rejects(
        stageCampaignImageUpload(
          database,
          storage,
          actor(b),
          a,
          item.id,
          bytes,
          mimeType,
        ),
        /campaign_media_access_denied/,
      );
      await assert.rejects(
        stageCampaignImageUpload(
          database,
          storage,
          actor(a),
          a,
          item.id,
          bytes.subarray(1),
          mimeType,
        ),
        /campaign_image_invalid/,
      );
      await assert.rejects(
        stageCampaignImageUpload(
          database,
          storage,
          actor(a),
          a,
          item.id,
          bytes,
          "text/html",
        ),
        /campaign_image_invalid/,
      );
      assert.deepEqual(await snapshot(), before);
      // A repeat PUT replaces only its private staged key; old attempt/object
      // cleanup must not remove the new object or another campaign's object.
      await stageCampaignImageUpload(
        database,
        storage,
        actor(a),
        a,
        item.id,
        bytes,
        mimeType,
      );
      const replacement = await getCampaignMedia(
        database,
        actor(a),
        a,
        item.id,
      );
      assert.notEqual(replacement.storageKey, staged.storageKey);
      assert.equal(await storage.exists(staged.storageKey), false);
      assert.equal(
        await new MediaRepository(database).hasUploadAttempt(staged.storageKey),
        false,
      );
      await verifyStored(replacement);
    }
    const bad = await createCampaignPendingMedia(database, actor(a), a, {
      filename: "synthetic-invalid.png",
      mimeType: "image/png",
      size: 40,
      authorId,
    });
    let before = await snapshot();
    await assert.rejects(
      stageCampaignImageUpload(
        database,
        storage,
        actor(a),
        a,
        bad.id,
        png.subarray(0, 40),
        "image/png",
      ),
      /campaign_image_invalid/,
    );
    assert.deepEqual(await snapshot(), before);
    const failure = await createCampaignPendingMedia(database, actor(a), a, {
      filename: "synthetic-db-fail.png",
      mimeType: "image/png",
      size: png.length,
      authorId,
    });
    before = await snapshot();
    await sql`CREATE FUNCTION public.synthetic_upload_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_upload_failure'; END; $$`.execute(
      database,
    );
    await sql`CREATE TRIGGER synthetic_upload_fail BEFORE UPDATE ON public.media FOR EACH ROW WHEN (OLD.filename='synthetic-db-fail.png') EXECUTE FUNCTION public.synthetic_upload_fail()`.execute(
      database,
    );
    await assert.rejects(
      stageCampaignImageUpload(
        database,
        storage,
        actor(a),
        a,
        failure.id,
        png,
        "image/png",
      ),
      /campaign_media_upload_failed/,
    );
    await sql`DROP TRIGGER synthetic_upload_fail ON public.media`.execute(
      database,
    );
    await sql`DROP FUNCTION public.synthetic_upload_fail()`.execute(database);
    assert.deepEqual(await snapshot(), before);
    // Real IAM denial, not a replacement Storage implementation. A failed
    // cleanup stays durably recorded instead of fabricating successful deletion.
    const deniedStorage = createStorage({ bucket: "not-permitted" });
    await assert.rejects(
      stageCampaignImageUpload(
        database,
        deniedStorage,
        actor(a),
        a,
        failure.id,
        png,
        "image/png",
      ),
      /campaign_media_upload_failed/,
    );
    const afterDenied = await snapshot();
    assert.deepEqual(afterDenied.media, before.media);
    assert.deepEqual(afterDenied.bindings, before.bindings);
    assert.deepEqual(afterDenied.keys, before.keys);
    assert.equal(afterDenied.attempts.length, before.attempts.length + 1);
    assert.equal(
      afterDenied.attempts.filter((attempt) => attempt.status === "cleanup")
        .length,
      1,
    );
    assert.deepEqual(
      (await listCampaignMedia(database, actor(a), a)).items,
      [],
    );
    assert.equal((await objectKeys()).length, 3);
    console.log(
      "campaign-media-upload: OK: actual EmDash S3 adapter with private scoped RustFS and PostgreSQL; normalized byte/hash readback, foreign and malformed no-write denial, repeat PUT cleanup, actual DB failure compensation, actual IAM failure with durable cleanup ledger. This is private staging, not HTTP/Core authorization or public delivery.",
    );
  }
} finally {
  await database.destroy();
}

import { z } from "astro/zod";
import { CoreIdentityError } from "./core-identity";
import {
  campaignEditorial,
  validCampaignEditorial,
} from "./campaign-editorial.mjs";

const input = z
  .object({
    data: campaignEditorial
      .extend({ action_id: z.uuid() })
      .refine(validCampaignEditorial),
    // Native create submits empty bylines and the operator-entered internal
    // slug. These may only echo our fixed defaults, never change metadata.
    bylines: z.array(z.never()).max(0).optional(),
    slug: z.uuid().optional(),
  })
  .strict()
  .refine(
    (value) => value.slug === undefined || value.slug === value.data.action_id,
  );

// Check raw input before upstream parsing can discard unknown metadata keys.
// Bound the stream itself, not only the untrusted Content-Length header.
export async function campaignCreateBody(request: Request) {
  const reader = request.clone().body?.getReader();
  if (!reader) throw new CoreIdentityError(403);
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 64 * 1024) throw new CoreIdentityError(403);
      chunks.push(value);
    }
    const parsed = input.safeParse(
      JSON.parse(Buffer.concat(chunks).toString("utf8")),
    );
    if (!parsed.success) throw new CoreIdentityError(403);
    return { data: parsed.data.data };
  } catch {
    throw new CoreIdentityError(403);
  } finally {
    // A tee branch's cancellation may wait for the original route reader.
    // Do not block a denied request waiting for an unread sibling stream.
    void reader.cancel().catch(() => {});
  }
}

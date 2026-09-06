import { LeonAidApiClient } from "@leonaid/api-client";
import { z } from "astro/zod";

export class CoreIdentityError extends Error {
  constructor(public readonly status: 401 | 403 | 503) {
    super(status === 503 ? "identity_unavailable" : "identity_denied");
  }
}

const membership = z.object({
  actionId: z.uuid(),
  actionName: z.string().max(400),
  role: z.enum(["charity_admin", "acquirer", "finance_reader", "driver"]),
  roleLabel: z.string().max(200),
});
const identity = z.object({
  userId: z.uuid(),
  displayName: z.string().trim().min(1).max(400),
  email: z.email().max(320),
  globalRoles: z.array(
    z.enum(["system_admin", "finance_reader", "finance_manager"]),
  ),
  actionMemberships: z.array(membership).max(1000),
  sessionExpiresAt: z.iso.datetime({ offset: true }),
  sessionLastSeenAt: z.iso.datetime({ offset: true }),
  freshLoginAt: z.iso.datetime({ offset: true }),
  freshUntil: z.iso.datetime({ offset: true }),
});

export function coreSessionCookie(request: Request): string {
  const header = request.headers.get("cookie") ?? "";
  if (header.length > 8192) throw new CoreIdentityError(401);
  const values = header.split(";").flatMap((part) => {
    const pair = part.trim();
    const separator = pair.indexOf("=");
    return pair.slice(0, separator) === "__Host-leonaid_session"
      ? [pair.slice(separator + 1)]
      : [];
  });
  if (values.length !== 1 || !/^[A-Za-z0-9_-]{32,256}$/.test(values[0])) {
    throw new CoreIdentityError(401);
  }
  return `__Host-leonaid_session=${values[0]}`;
}

// Transport remains in the generated client. The wrapper bounds the actual
// response body and disallows redirects so cookies cannot leave the fixed Core.
const client = new LeonAidApiClient("http://api:8000", async (input, init) => {
  const response = await fetch(input, { ...init, redirect: "error" });
  if (!response.ok) {
    await response.body?.cancel();
    throw new CoreIdentityError(
      response.status === 401 || response.status === 403
        ? response.status
        : 503,
    );
  }
  if (!response.headers.get("content-type")?.startsWith("application/json")) {
    await response.body?.cancel();
    throw new CoreIdentityError(503);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new CoreIdentityError(503);
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 64 * 1024) throw new CoreIdentityError(503);
      chunks.push(value);
    }
  } finally {
    await reader.cancel();
  }
  return new Response(Buffer.concat(chunks), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});

export async function readCoreIdentity(request: Request) {
  const cookie = coreSessionCookie(request);
  try {
    const result = identity.safeParse(
      await client.getCurrentIdentity({
        headers: { Cookie: cookie },
        signal: AbortSignal.timeout(2000),
      }),
    );
    if (!result.success) throw new CoreIdentityError(503);
    const profile = result.data;
    if (Date.parse(profile.sessionExpiresAt) <= Date.now()) {
      throw new CoreIdentityError(401);
    }
    const role = profile.globalRoles.includes("system_admin")
      ? 50
      : profile.actionMemberships.some((item) => item.role === "charity_admin")
        ? 40
        : null;
    if (!role) throw new CoreIdentityError(403);
    return { ...profile, role };
  } catch (error) {
    if (error instanceof CoreIdentityError) throw error;
    // Never leak schema failures, dependency URLs, cookies or profile contents.
    throw new CoreIdentityError(503);
  }
}

// Core evaluates lifecycle and publication windows with its own clock. This is
// a fresh management read, not authority inferred from CMS status or timestamps.
export async function requireCorePublication(
  request: Request,
  actionId: string,
) {
  if (!z.uuid().safeParse(actionId).success) throw new CoreIdentityError(403);
  try {
    const result = z
      .object({ id: z.uuid(), isPublished: z.boolean() })
      .safeParse(
        await client.getCharityAction(actionId, {
          headers: { Cookie: coreSessionCookie(request) },
          signal: AbortSignal.timeout(2000),
        }),
      );
    if (!result.success || result.data.id !== actionId)
      throw new CoreIdentityError(503);
    if (!result.data.isPublished) throw new CoreIdentityError(403);
  } catch (error) {
    if (error instanceof CoreIdentityError) throw error;
    throw new CoreIdentityError(503);
  }
}

// Role-based entry of the admin host (specs/multi-domain §6.7). Caddy serves
// this page for `/` on app.<domain>; invitations link it directly. No
// session → the sign-in page; a session → the member's start area, which
// Core computes (landingPath). Server-side only: no client flash, no service
// worker involved.
import type { APIRoute } from "astro";
import { ApiError, LeonAidApiClient } from "@leonaid/api-client";
import { ADMIN_BASE } from "@leonaid/ui/base-paths";
import { entryDestination } from "../../lib/entry";

const SESSION_COOKIE = "__Host-leonaid_session";
const timeoutMilliseconds = 5_000;

function sessionCookie(header: string | null): string | null {
  for (const part of (header ?? "").split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === SESSION_COOKIE && value.length > 0) return value.join("=");
  }
  return null;
}

function redirect(location: string): Response {
  return new Response(null, {
    status: 302,
    headers: {
      Location: location,
      "Cache-Control": "no-store",
      Vary: "Cookie",
    },
  });
}

function unavailable(): Response {
  return new Response("LeonAid ist gerade nicht erreichbar.", {
    status: 503,
    headers: { "Cache-Control": "no-store", "Retry-After": "30" },
  });
}

export const GET: APIRoute = async ({ request }) => {
  const session = sessionCookie(request.headers.get("cookie"));
  if (!session) return redirect("/login");
  const core = process.env.CORE_API_URL?.trim() || "http://api:8000";
  try {
    // Only the session cookie reaches Core, never other cookies of the host.
    const identity = await new LeonAidApiClient(core).getCurrentIdentity({
      headers: {
        Cookie: `${SESSION_COOKIE}=${session}`,
        "X-Request-ID": `entry:${crypto.randomUUID()}`,
      },
      signal: AbortSignal.timeout(timeoutMilliseconds),
    });
    return redirect(entryDestination(identity.landingPath, ADMIN_BASE));
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 401 || error.status === 403)
    )
      return redirect("/login");
    console.warn("entry_identity_unavailable");
    return unavailable();
  }
};

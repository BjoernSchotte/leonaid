// Role-based entry of the admin host (specs/multi-domain §6.7). Caddy serves
// this page for `/` on app.<domain>; invitations link it directly. No
// session → the sign-in page; a session → the member's start area, which
// Core computes (landingPath). Server-side only: no client flash, no service
// worker involved.
import type { APIRoute } from "astro";
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

export const GET: APIRoute = async ({ request }) => {
  const session = sessionCookie(request.headers.get("cookie"));
  if (!session) return redirect("/login");
  const core = process.env.CORE_API_URL?.trim() || "http://api:8000";
  let response: Response;
  try {
    // Only the session cookie reaches Core, never other cookies of the host.
    response = await fetch(`${core}/api/v1/identity/me`, {
      headers: {
        Cookie: `${SESSION_COOKIE}=${session}`,
        "X-Request-ID": `entry:${crypto.randomUUID()}`,
      },
      signal: AbortSignal.timeout(timeoutMilliseconds),
    });
  } catch {
    console.warn("entry_identity_unavailable");
    return new Response("LeonAid ist gerade nicht erreichbar.", {
      status: 503,
      headers: { "Cache-Control": "no-store", "Retry-After": "30" },
    });
  }
  if (response.status === 401 || response.status === 403) {
    return redirect("/login");
  }
  if (!response.ok) {
    console.warn("entry_identity_failed");
    return new Response("LeonAid ist gerade nicht erreichbar.", {
      status: 503,
      headers: { "Cache-Control": "no-store", "Retry-After": "30" },
    });
  }
  const identity = (await response.json()) as { landingPath?: unknown };
  return redirect(entryDestination(identity.landingPath, ADMIN_BASE));
};

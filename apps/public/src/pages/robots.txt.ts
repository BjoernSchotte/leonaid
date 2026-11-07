import type { APIRoute } from "astro";
import { hasPublicHost, publicRobots } from "../lib/site-hosts";

export const GET: APIRoute = ({ url }) =>
  new Response(publicRobots(url.origin, hasPublicHost()), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=300",
    },
  });

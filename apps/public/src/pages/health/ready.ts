import type { APIRoute } from "astro";

export const GET: APIRoute = () =>
  new Response("ready", {
    status: 200,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
    },
  });

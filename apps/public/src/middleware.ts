import { defineMiddleware } from "astro:middleware";
import { guardOrderBody, isOrderSubmission } from "./lib/order-body";

export const onRequest = defineMiddleware(async ({ request }, next) => {
  if (!isOrderSubmission(request)) return next();
  const response = (await guardOrderBody(request)) ?? (await next());
  response.headers.set("Cache-Control", "no-store");
  return response;
});

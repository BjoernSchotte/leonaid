import { ActionError, defineAction } from "astro:actions";
import { z } from "astro/zod";

import { isMissingPublicAction, resolvePublicAction } from "../lib/core";

const publicRouteValue = z
  .string()
  .trim()
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/)
  .max(160);

export const server = {
  resolvePublicAction: defineAction({
    input: z.object({
      routeKind: z.enum(["alias", "archive"]),
      routeValue: publicRouteValue,
    }),
    handler: async ({ routeKind, routeValue }) => {
      try {
        return await resolvePublicAction(routeKind, routeValue);
      } catch (error) {
        if (isMissingPublicAction(error)) {
          throw new ActionError({
            code: "NOT_FOUND",
            message: "Diese öffentliche Aktionsseite wurde nicht gefunden.",
          });
        }
        throw new ActionError({
          code: "SERVICE_UNAVAILABLE",
          message: "Die Aktionsdaten sind gerade nicht erreichbar.",
        });
      }
    },
  }),
};

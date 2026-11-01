import { ActionError, defineAction } from "astro:actions";
import { z } from "astro/zod";

import { ApiError } from "@leonaid/api-client";

import {
  isMissingPublicAction,
  resolvePublicAction,
  submitPublicOrder,
} from "../lib/core";

const publicRouteValue = z
  .string()
  .trim()
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/)
  .max(160);

const optionalText = (maximum: number) =>
  z.string().trim().max(maximum).optional();
const requiredText = (maximum: number) => z.string().trim().min(1).max(maximum);

function publicOrderActionError(error: unknown): ActionError {
  if (error instanceof ApiError) {
    const code =
      error.status === 403
        ? "FORBIDDEN"
        : error.status === 409
          ? "CONFLICT"
          : error.status === 422
            ? "UNPROCESSABLE_CONTENT"
            : error.status === 429
              ? "TOO_MANY_REQUESTS"
              : error.status === 503
                ? "SERVICE_UNAVAILABLE"
                : "INTERNAL_SERVER_ERROR";
    return new ActionError({ code, message: error.detail.message });
  }
  return new ActionError({
    code: "SERVICE_UNAVAILABLE",
    message:
      "Die Bestellung konnte gerade nicht übermittelt werden. Deine Eingaben bleiben erhalten.",
  });
}

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
  createPublicOrder: defineAction({
    accept: "form",
    input: z.object({
      publicAlias: publicRouteValue,
      accessToken: z.string().min(32).max(2_048),
      commandId: z.uuid(),
      companyName: optionalText(300),
      givenName: requiredText(200),
      familyName: requiredText(200),
      email: z.email().trim().max(320),
      phone: optionalText(40),
      // Only rendered (and required by Core) for actions with delivery.
      deliveryRecipientName: optionalText(300),
      deliveryStreetLine1: optionalText(300),
      deliveryPostalCode: optionalText(24),
      deliveryCity: optionalText(200),
      deliveryWindowId: z.uuid().optional(),
      deliveryContactName: optionalText(200),
      deliveryContactPhone: optionalText(40),
      billingSameAsDelivery: z.boolean(),
      invoiceRecipientName: optionalText(300),
      invoiceStreetLine1: optionalText(300),
      invoicePostalCode: optionalText(24),
      invoiceCity: optionalText(200),
      invoiceEmail: optionalText(320),
      offeringId: z.array(z.uuid()).min(1).max(20),
      quantity: z.array(z.number().int().min(0).max(5_000)).min(1).max(20),
      unit: z
        .array(z.enum(["box", "piece", "package", "sponsoring"]))
        .min(1)
        .max(20),
      quotedUnitPriceMinor: z.array(z.number().int().min(0)).min(1).max(20),
      message: optionalText(1_000),
      privacyAcknowledged: z.boolean().refine(Boolean, {
        message: "Bitte bestätige die Hinweise zur Datenverarbeitung.",
      }),
      bindingOrderConfirmed: z.boolean().refine(Boolean, {
        message: "Bitte bestätige die verbindliche Bestellung.",
      }),
      privacyNoticeVersion: z.string().regex(/^[a-z0-9][a-z0-9._-]{2,63}$/),
      website: optionalText(300),
    }),
    handler: async (input, context) => {
      if (
        input.offeringId.length !== input.quantity.length ||
        input.offeringId.length !== input.unit.length ||
        input.offeringId.length !== input.quotedUnitPriceMinor.length
      ) {
        throw new ActionError({
          code: "BAD_REQUEST",
          message:
            "Die Bestellpositionen sind unvollständig. Lade die Seite neu.",
        });
      }
      const lines = input.offeringId
        .map((offeringId, index) => ({
          offeringId,
          quantity: input.quantity[index],
          unit: input.unit[index],
          quotedUnitPriceMinor: input.quotedUnitPriceMinor[index],
        }))
        .filter((line) => line.quantity > 0);
      if (lines.length === 0) {
        throw new ActionError({
          code: "UNPROCESSABLE_CONTENT",
          message: "Wähle mindestens ein Angebot und eine Menge aus.",
        });
      }
      const deliveryFields = [
        input.deliveryRecipientName,
        input.deliveryStreetLine1,
        input.deliveryPostalCode,
        input.deliveryCity,
      ];
      const deliveryRecipient = deliveryFields.every(Boolean)
        ? {
            recipientName: input.deliveryRecipientName ?? "",
            streetLine1: input.deliveryStreetLine1 ?? "",
            postalCode: input.deliveryPostalCode ?? "",
            city: input.deliveryCity ?? "",
            countryCode: "DE",
          }
        : null;
      if (!deliveryRecipient && deliveryFields.some(Boolean)) {
        throw new ActionError({
          code: "UNPROCESSABLE_CONTENT",
          message: "Bitte vervollständige die Lieferadresse.",
        });
      }
      if (input.billingSameAsDelivery && !deliveryRecipient) {
        throw new ActionError({
          code: "UNPROCESSABLE_CONTENT",
          message:
            "Bitte gib eine Lieferadresse oder eine Rechnungsadresse an.",
        });
      }
      const invoiceRecipient =
        input.billingSameAsDelivery && deliveryRecipient
          ? { ...deliveryRecipient, email: input.email }
          : {
              recipientName: input.invoiceRecipientName ?? "",
              streetLine1: input.invoiceStreetLine1 ?? "",
              postalCode: input.invoicePostalCode ?? "",
              city: input.invoiceCity ?? "",
              email: input.invoiceEmail ?? input.email,
              countryCode: "DE",
            };
      try {
        return await submitPublicOrder(
          input.publicAlias,
          {
            accessToken: input.accessToken,
            commandId: input.commandId,
            party: {
              companyName: input.companyName || null,
              givenName: input.givenName,
              familyName: input.familyName,
              email: input.email,
              phone: input.phone || null,
            },
            ...(deliveryRecipient ? { deliveryRecipient } : {}),
            ...(input.deliveryWindowId
              ? { deliveryWindowId: input.deliveryWindowId }
              : {}),
            ...(input.deliveryContactName || input.deliveryContactPhone
              ? {
                  deliveryContact: {
                    name: input.deliveryContactName || null,
                    phone: input.deliveryContactPhone || null,
                  },
                }
              : {}),
            invoiceRecipient,
            lines,
            message: input.message || null,
            privacyAcknowledged: input.privacyAcknowledged,
            bindingOrderConfirmed: input.bindingOrderConfirmed,
            privacyNoticeVersion: input.privacyNoticeVersion,
            website: input.website || null,
          },
          {
            forwardedFor:
              context.request.headers.get("x-forwarded-for") ??
              context.clientAddress,
            userAgent: context.request.headers.get("user-agent") ?? undefined,
          },
        );
      } catch (error) {
        throw publicOrderActionError(error);
      }
    },
  }),
};

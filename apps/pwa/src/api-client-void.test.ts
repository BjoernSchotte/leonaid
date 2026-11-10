/*
 * The generated client's operations without a response body (204), e.g.
 * recordMyTourReads (krapfentaxi-touren §10). Lives in the PWA suite, the
 * client's consumer, so it runs with the existing test path.
 */
import { describe, expect, it } from "vitest";

import { ApiError, LeonAidApiClient } from "@leonaid/api-client";

const ACTION = "20000000-0000-4000-8000-000000000001";
const body = {
  reads: [
    {
      readAt: "2026-12-05T08:00:00Z",
      windowId: "70000000-0000-4000-8000-000000000001",
    },
  ],
};

function client(response: Response, calls: Request[] = []) {
  return new LeonAidApiClient(
    "https://leonaid.invalid/",
    async (input, init) => {
      calls.push(new Request(input, init));
      return response;
    },
  );
}

describe("requestVoid (204 operations)", () => {
  it("resolves on 204 and sends the body as JSON", async () => {
    const calls: Request[] = [];
    await expect(
      client(new Response(null, { status: 204 }), calls).recordMyTourReads(
        ACTION,
        body,
      ),
    ).resolves.toBeUndefined();
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    expect(calls[0].url).toBe(
      `https://leonaid.invalid/api/v1/actions/${ACTION}/my-tour/reads`,
    );
    expect(calls[0].headers.get("content-type")).toBe("application/json");
    expect(await calls[0].json()).toEqual(body);
  });

  it("refuses a 200 from a proxy or static fallback", async () => {
    const error = await client(
      new Response("<html></html>", {
        headers: { "content-type": "text/html" },
        status: 200,
      }),
    )
      .recordMyTourReads(ACTION, body)
      .catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(200);
    expect((error as ApiError).detail.code).toBe("unexpected_response_type");
  });

  it("turns an error answer into an ApiError with Core's code", async () => {
    const error = await client(
      new Response(
        JSON.stringify({
          error: {
            code: "tour_read_out_of_range",
            message: "Bitte Datum und Uhrzeit des Geräts prüfen.",
            requestId: "req-1",
          },
        }),
        { headers: { "content-type": "application/json" }, status: 422 },
      ),
    )
      .recordMyTourReads(ACTION, body)
      .catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).detail.code).toBe("tour_read_out_of_range");
  });
});

// @vitest-environment jsdom
/*
 * The flags of the device's last online start (krapfentaxi-touren D14 g):
 * an offline start settles on them, and reconnecting keeps them until Core
 * answers, so "Meine Tour" never flickers through "all off". Core's answer
 * then wins, also when it says off.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it } from "vitest";

import type {
  CurrentIdentityResponse,
  FeatureFlagEvaluationListResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  FEATURE_FLAGS,
  FeatureFlagProvider,
  useLeonAidEvaluatedFlag,
  useLeonAidSettledFlag,
} from "@leonaid/features";

afterEach(cleanup);

const identity = {
  actionMemberships: [],
  globalRoles: [],
  userId: "10000000-0000-4000-8000-000000000007",
} as unknown as CurrentIdentityResponse;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
}

function evaluation(enabled: boolean): FeatureFlagEvaluationListResponse {
  return {
    flags: [{ enabled, key: FEATURE_FLAGS.deliveryTours }],
  } as unknown as FeatureFlagEvaluationListResponse;
}

function setup() {
  const answers: ReturnType<
    typeof deferred<FeatureFlagEvaluationListResponse>
  >[] = [];
  const client = {
    getFeatureFlagEvaluations: () => {
      const answer = deferred<FeatureFlagEvaluationListResponse>();
      answers.push(answer);
      return answer.promise;
    },
  } as unknown as LeonAidApiClient;
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const seen: (boolean | null)[] = [];
  const evaluated: (boolean | null)[] = [];
  function Probe() {
    seen.push(useLeonAidSettledFlag(FEATURE_FLAGS.deliveryTours));
    evaluated.push(useLeonAidEvaluatedFlag(FEATURE_FLAGS.deliveryTours));
    return null;
  }
  render(
    createElement(
      QueryClientProvider,
      { client: queries },
      createElement(
        FeatureFlagProvider,
        {
          cached: new Map([[FEATURE_FLAGS.deliveryTours, true]]),
          client,
          identity,
          surface: "pwa",
        },
        createElement(Probe),
      ),
    ),
  );
  return { answers, evaluated, queries, seen };
}

const settle = () => act(async () => new Promise((done) => setTimeout(done)));

describe("cached flags", () => {
  it("an offline start settles on the cached flags and reconnects without flicker", async () => {
    const { answers, evaluated, queries, seen } = setup();
    await waitFor(() => expect(answers).toHaveLength(1));
    await act(async () => answers[0].reject(new TypeError("Failed to fetch")));
    await settle();
    expect(seen.at(-1)).toBe(true);
    // Deletions never follow the cached values.
    expect(evaluated.at(-1)).toBeNull();

    // Back online: the refetch is under way, then Core answers.
    const from = seen.length;
    await act(async () => {
      void queries.refetchQueries({ queryKey: ["feature-flags"] });
    });
    await waitFor(() => expect(answers).toHaveLength(2));
    await act(async () => answers[1].resolve(evaluation(true)));
    await waitFor(() => expect(evaluated.at(-1)).toBe(true));
    await settle();
    expect(seen.slice(from).length).toBeGreaterThan(0);
    expect(seen.slice(from).every((value) => value === true)).toBe(true);
  });

  it("Core's answer wins over the cached flags, also when it says off", async () => {
    const { answers, evaluated, queries, seen } = setup();
    await waitFor(() => expect(answers).toHaveLength(1));
    await act(async () => answers[0].reject(new TypeError("Failed to fetch")));
    await settle();
    expect(seen.at(-1)).toBe(true);
    await act(async () => {
      void queries.refetchQueries({ queryKey: ["feature-flags"] });
    });
    await waitFor(() => expect(answers).toHaveLength(2));
    await act(async () => answers[1].resolve(evaluation(false)));
    await waitFor(() => expect(seen.at(-1)).toBe(false));
    expect(evaluated.at(-1)).toBe(false);
  });
});

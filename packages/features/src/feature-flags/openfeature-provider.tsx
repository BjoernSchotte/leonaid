import { useQuery } from "@tanstack/react-query";
import {
  OpenFeature,
  OpenFeatureProvider,
  TypedInMemoryProvider,
  useBooleanFlagValue,
} from "@openfeature/react-sdk";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type {
  CurrentIdentityResponse,
  FeatureFlagEvaluationResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";

export const FEATURE_FLAG_DOMAIN = "leonaid";

export const FEATURE_FLAGS = {
  deliveryTours: "delivery.tours",
  previewNotice: "admin.preview_notice",
  pwaOfflineQueue: "pwa.offline_queue",
  systemStatusPanel: "admin.system_status_panel",
} as const;

export type FeatureFlagKey = (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS];

const disabledConfiguration = featureConfiguration(new Map());
const browserProvider = new TypedInMemoryProvider(disabledConfiguration);

OpenFeature.setProvider(FEATURE_FLAG_DOMAIN, browserProvider);

function featureConfiguration(
  evaluations: ReadonlyMap<FeatureFlagKey, FeatureFlagEvaluationResponse>,
) {
  function configured(key: FeatureFlagKey) {
    const enabled = evaluations.get(key)?.enabled ?? false;
    return {
      defaultVariant: enabled ? ("enabled" as const) : ("disabled" as const),
      disabled: false,
      variants: {
        disabled: false,
        enabled: true,
      },
    };
  }

  return {
    [FEATURE_FLAGS.deliveryTours]: configured(FEATURE_FLAGS.deliveryTours),
    [FEATURE_FLAGS.previewNotice]: configured(FEATURE_FLAGS.previewNotice),
    [FEATURE_FLAGS.pwaOfflineQueue]: configured(FEATURE_FLAGS.pwaOfflineQueue),
    [FEATURE_FLAGS.systemStatusPanel]: configured(
      FEATURE_FLAGS.systemStatusPanel,
    ),
  };
}

/**
 * The evaluated flags once known: null while the evaluation is loading,
 * an empty map when it or applying it failed (every flag off). Outside a provider every
 * flag is settled and off.
 */
const ALL_OFF: ReadonlyMap<string, boolean> = new Map();
const SettledFlagsContext = createContext<ReadonlyMap<string, boolean> | null>(
  new Map(),
);
/** Core's own answer only: null until it arrived (or without one). */
const EvaluatedFlagsContext = createContext<ReadonlyMap<
  string,
  boolean
> | null>(null);

export interface FeatureFlagProviderProps {
  readonly children: ReactNode;
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
  readonly surface: "web" | "pwa";
  /**
   * Values to settle on when the evaluation fails, e.g. the PWA's device
   * copy of its last online start while Core is out of reach; without
   * them every flag is off.
   */
  readonly cached?: ReadonlyMap<string, boolean> | null;
}

export function FeatureFlagProvider({
  cached,
  children,
  client,
  identity,
  surface,
}: FeatureFlagProviderProps) {
  const evaluations = useQuery({
    queryFn: () => client.getFeatureFlagEvaluations({ surface }),
    queryKey: ["feature-flags", surface],
    // Offline the request fails instead of pausing, so the flags settle
    // (all off) and gated views do not wait for a network that is gone.
    networkMode: "always",
    staleTime: 5_000,
  });

  useEffect(() => {
    void OpenFeature.setContext(FEATURE_FLAG_DOMAIN, {
      roles: [
        ...identity.globalRoles,
        ...new Set(identity.actionMemberships.map((item) => item.role)),
      ],
      surface,
      targetingKey: identity.userId,
    });
  }, [identity, surface]);

  // The values OpenFeature holds. A reload with new values keeps the old
  // ones until the new ones are in, so gated views do not remount.
  const [applied, setApplied] = useState<ReadonlyMap<string, boolean> | null>(
    null,
  );
  useEffect(() => {
    const data = evaluations.data;
    if (!data) return;
    const values = new Map(data.flags.map((flag) => [flag.key, flag] as const));
    let live = true;
    // Settled only once OpenFeature holds the same values, so a view that
    // waits for it never sees a flag still at its default.
    // If OpenFeature refuses the values, it keeps what it held: the values
    // applied before, or all off on the first load. Settle on those, so
    // gated views do not wait forever.
    void browserProvider.putConfiguration(featureConfiguration(values)).then(
      () => {
        if (!live) return;
        setApplied(new Map(data.flags.map((flag) => [flag.key, flag.enabled])));
      },
      () => {
        if (!live) return;
        setApplied((current) => current ?? ALL_OFF);
      },
    );
    return () => {
      live = false;
    };
  }, [evaluations.data]);

  // Once an evaluation failed, the fallback stays until Core answers: a
  // refetch after an error is "pending" again, and gated views must not
  // fall back to their skeleton (or flicker) while it runs.
  const failed = evaluations.isError || evaluations.errorUpdateCount > 0;
  const settled = applied ?? (failed ? (cached ?? ALL_OFF) : null);
  const evaluated = useMemo(
    () =>
      evaluations.data
        ? new Map(
            evaluations.data.flags.map((flag) => [flag.key, flag.enabled]),
          )
        : null,
    [evaluations.data],
  );

  return (
    <OpenFeatureProvider domain={FEATURE_FLAG_DOMAIN}>
      <EvaluatedFlagsContext.Provider value={evaluated}>
        <SettledFlagsContext.Provider value={settled}>
          {children}
        </SettledFlagsContext.Provider>
      </EvaluatedFlagsContext.Provider>
    </OpenFeatureProvider>
  );
}

/**
 * A flag that gates which view renders: null until the evaluation has
 * arrived (or failed), then its value. Unlike `useLeonAidBooleanFlag`, it
 * never reports the default first, so a gated view does not flash.
 */
export function useLeonAidSettledFlag(key: FeatureFlagKey): boolean | null {
  const settled = useContext(SettledFlagsContext);
  return settled ? (settled.get(key) ?? false) : null;
}

/**
 * A flag as Core last answered it: null while no answer arrived (loading,
 * offline, failed). For decisions that delete data, which must never
 * follow a fallback.
 */
export function useLeonAidEvaluatedFlag(key: FeatureFlagKey): boolean | null {
  const evaluated = useContext(EvaluatedFlagsContext);
  return evaluated ? (evaluated.get(key) ?? false) : null;
}

export function useLeonAidBooleanFlag(
  key: FeatureFlagKey,
  defaultValue = false,
) {
  return useBooleanFlagValue(key, defaultValue);
}

export function PreviewNotice() {
  const enabled = useLeonAidBooleanFlag(FEATURE_FLAGS.previewNotice);
  if (!enabled) return null;

  return (
    <aside className="feature-preview-notice" data-testid="preview-notice">
      <span>PoC-Preview</span>
      <p>
        Diese Oberfläche wird mit echten Abläufen erprobt. Rückmeldungen helfen
        uns, den nächsten Ausbau gezielt zu schneiden.
      </p>
    </aside>
  );
}

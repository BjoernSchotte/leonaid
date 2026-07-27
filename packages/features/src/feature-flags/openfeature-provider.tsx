import { useQuery } from "@tanstack/react-query";
import {
  OpenFeature,
  OpenFeatureProvider,
  TypedInMemoryProvider,
  useBooleanFlagValue,
} from "@openfeature/react-sdk";
import { useEffect, type ReactNode } from "react";

import type {
  CurrentIdentityResponse,
  FeatureFlagEvaluationResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";

export const FEATURE_FLAG_DOMAIN = "leonaid";

export const FEATURE_FLAGS = {
  previewNotice: "admin.preview_notice",
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
    [FEATURE_FLAGS.previewNotice]: configured(FEATURE_FLAGS.previewNotice),
    [FEATURE_FLAGS.systemStatusPanel]: configured(
      FEATURE_FLAGS.systemStatusPanel,
    ),
  };
}

export interface FeatureFlagProviderProps {
  readonly children: ReactNode;
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
  readonly surface: "web" | "pwa";
}

export function FeatureFlagProvider({
  children,
  client,
  identity,
  surface,
}: FeatureFlagProviderProps) {
  const evaluations = useQuery({
    queryFn: () => client.getFeatureFlagEvaluations({ surface }),
    queryKey: ["feature-flags", surface],
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

  useEffect(() => {
    if (!evaluations.data) return;
    const values = new Map(
      evaluations.data.flags.map((flag) => [flag.key, flag] as const),
    );
    void browserProvider.putConfiguration(featureConfiguration(values));
  }, [evaluations.data]);

  return (
    <OpenFeatureProvider domain={FEATURE_FLAG_DOMAIN}>
      {children}
    </OpenFeatureProvider>
  );
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

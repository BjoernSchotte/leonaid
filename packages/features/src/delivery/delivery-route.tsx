import { useEffect, type ReactNode } from "react";

import type { LeonAidApiClient } from "@leonaid/api-client";
import { SkeletonRows } from "@leonaid/ui";
import { pwaHref } from "@leonaid/ui/base-paths";

import {
  FEATURE_FLAGS,
  useLeonAidSettledFlag,
} from "../feature-flags/openfeature-provider";
import { navigateInPage } from "../shared/location";
import { DeliveryBoardPage } from "./delivery-board";
import { MyTourPage } from "./my-tour";

export interface PwaDeliveryPageProps {
  readonly client: LeonAidApiClient;
  readonly actionId: string;
  readonly actions?: readonly {
    readonly actionId: string;
    readonly actionName: string;
  }[];
  readonly offline: boolean;
}

/**
 * The PWA delivery route: "Meine Tour" with the flag `delivery.tours`
 * (spec krapfentaxi-touren §7), else the delivery board. Until the flag is
 * known it shows a skeleton, so neither page loads (and audits a read) for
 * nothing.
 */
export function PwaDeliveryPage(props: PwaDeliveryPageProps) {
  const tours = useLeonAidSettledFlag(FEATURE_FLAGS.deliveryTours);
  if (tours === null) {
    return (
      <div className="delivery" data-zone="delivery">
        <SkeletonRows rows={5} />
      </div>
    );
  }
  return tours ? (
    <MyTourPage {...props} />
  ) : (
    <DeliveryBoardPage {...props} surface="pwa" />
  );
}

/**
 * The PWA start (`/app/`) of a user who only drives in the selected action
 * (critique-driver P0-2, D19 3a): with `delivery.tours` the URL moves to the
 * delivery route and the tour shows; without it the usual start page.
 * Until the flag is known a skeleton shows, never the acquirer start page.
 */
export function PwaDriverStart({
  delivery,
  fallback,
}: {
  readonly delivery: ReactNode;
  readonly fallback: ReactNode;
}) {
  const tours = useLeonAidSettledFlag(FEATURE_FLAGS.deliveryTours);
  useEffect(() => {
    if (!tours) return;
    navigateInPage(`${pwaHref("delivery")}${window.location.search}`, {
      replace: true,
    });
  }, [tours]);
  if (tours === null) {
    return (
      <div className="delivery" data-zone="delivery">
        <SkeletonRows rows={5} />
      </div>
    );
  }
  return tours ? delivery : fallback;
}

/**
 * Whether the user drives in the selected action (`?action=`, else their
 * first membership), and whether that is their only role there.
 */
export function driverStanding(
  memberships: readonly { readonly actionId: string; readonly role: string }[],
  currentActionId: string,
): { readonly driver: boolean; readonly driverOnly: boolean } {
  const selected = memberships.some(
    (membership) => membership.actionId === currentActionId,
  )
    ? currentActionId
    : memberships[0]?.actionId;
  const roles = memberships
    .filter((membership) => membership.actionId === selected)
    .map((membership) => membership.role);
  const driver = roles.includes("driver");
  return {
    driver,
    driverOnly: driver && roles.every((role) => role === "driver"),
  };
}

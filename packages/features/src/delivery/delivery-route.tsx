import type { LeonAidApiClient } from "@leonaid/api-client";
import { SkeletonRows } from "@leonaid/ui";

import {
  FEATURE_FLAGS,
  useLeonAidSettledFlag,
} from "../feature-flags/openfeature-provider";
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

import type { CurrentIdentityResponse } from "@leonaid/api-client";
import { ExternalLink } from "lucide-react";

import { buttonClassName, Icon } from "@leonaid/ui";

type CampaignIdentity = Pick<
  CurrentIdentityResponse,
  "globalRoles" | "actionMemberships" | "navigation"
>;

// The server lists the microsite entry only when the installation runs the
// CMS (LEONAID_CMS_ENABLED). Without it /_emdash has no upstream (502).
export function cmsAvailable(identity: Pick<CampaignIdentity, "navigation">) {
  return identity.navigation.some(
    (item) => item.surface === "web" && item.key === "microsite",
  );
}

export function campaignEditorHref(
  identity: CampaignIdentity,
  actionId: string,
) {
  if (
    !cmsAvailable(identity) ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      actionId,
    ) ||
    (!identity.globalRoles.includes("system_admin") &&
      !identity.actionMemberships.some(
        (membership) =>
          membership.actionId === actionId &&
          membership.role === "charity_admin",
      ))
  )
    return undefined;
  return `/_emdash/admin/campaigns/${actionId}`;
}

export function CampaignEditorLink({
  actionId,
  identity,
}: {
  readonly actionId: string;
  readonly identity: CampaignIdentity;
}) {
  const href = campaignEditorHref(identity, actionId);
  if (!href) return null;

  return (
    // Same as the action page header: a ghost link beside the page's one
    // primary action.
    <a className={buttonClassName({ variant: "ghost" })} href={href}>
      <Icon icon={ExternalLink} size={16} />
      <span className="btn-label">Microsite bearbeiten</span>
    </a>
  );
}

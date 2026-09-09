import type { CurrentIdentityResponse } from "@leonaid/api-client";

type CampaignIdentity = Pick<
  CurrentIdentityResponse,
  "globalRoles" | "actionMemberships"
>;

export function campaignEditorHref(
  identity: CampaignIdentity,
  actionId: string,
) {
  if (
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
    <a className="ui-button ui-button--secondary" href={href}>
      Microsite bearbeiten
    </a>
  );
}

import type { CurrentIdentityResponse } from "@leonaid/api-client";

export function CampaignEditorLink({
  actionId,
  identity,
}: {
  readonly actionId: string;
  readonly identity: Pick<
    CurrentIdentityResponse,
    "globalRoles" | "actionMemberships"
  >;
}) {
  if (
    !actionId ||
    (!identity.globalRoles.includes("system_admin") &&
      !identity.actionMemberships.some(
        (membership) =>
          membership.actionId === actionId &&
          membership.role === "charity_admin",
      ))
  )
    return null;

  return (
    <a
      className="ui-button ui-button--secondary"
      href={`/_emdash/admin/campaigns/${encodeURIComponent(actionId)}`}
    >
      Microsite bearbeiten
    </a>
  );
}

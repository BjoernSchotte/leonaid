import type { LeonAidApiClient } from "@leonaid/api-client";
import { AccessMembersPanel } from "../shared/access-members";

export function ListMembersPanel({
  client,
  listId,
  actionScoped,
}: {
  client: LeonAidApiClient;
  listId: string;
  actionScoped: boolean;
}) {
  return (
    <AccessMembersPanel
      client={client}
      objectId={listId}
      kind="task-list"
      actionScoped={actionScoped}
    />
  );
}

import type { LeonAidApiClient } from "@leonaid/api-client";

import {
  AccessMembersPanel,
  type AccessMemberSource,
} from "../shared/access-members";

function taskListSource(
  client: LeonAidApiClient,
  listId: string,
): AccessMemberSource {
  return {
    queryKey: "task-members",
    label: "Listenmitglieder",
    accessLabel: "Listenzugriff",
    subject: "diese Liste",
    list: (search, offset) =>
      client.listTaskListMembers(listId, { search, offset }),
    change: (command, expectedRevision, idempotencyKey) => {
      const common = { expectedRevision, idempotencyKey };
      return "email" in command
        ? client.setTaskListMemberByEmail(listId, { ...common, ...command })
        : client.setTaskListMember(listId, { ...common, ...command });
    },
    dependentQueryKeys: [
      ["task-assignees", listId],
      ["task-list", listId],
    ],
  };
}

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
      objectId={listId}
      source={taskListSource(client, listId)}
      actionScoped={actionScoped}
    />
  );
}

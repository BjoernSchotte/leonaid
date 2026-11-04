import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";

import type { Case, LeonAidApiClient } from "@leonaid/api-client";
import { Button, DetailProps, DetailSection, NextStep } from "@leonaid/ui";

import { InboxComments } from "./comments";
import { InboxContact } from "./contact";
import { fullName, receivedLabel, type Address } from "./inbox-model";
import { InboxMaterials, useMaterialReferences } from "./materials";
import { InboxTasks, useTaskReferences } from "./tasks";

export interface CaseDetailProps {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly item: Case;
  readonly actionName: string;
  readonly taskBasePath: string;
  readonly takingOver: boolean;
  readonly onClose: (item: Case) => void;
  readonly onTakeOver: (item: Case) => void;
}

/** Pane body of one inquiry, in the prototype's order. */
export function CaseDetail({
  actionName,
  address,
  client,
  item,
  onClose,
  onTakeOver,
  takingOver,
  taskBasePath,
}: CaseDetailProps) {
  const permissions = useQuery({
    queryKey: ["inbox-permissions", item.id],
    queryFn: () => client.getInboxCasePermissions(item.id),
    retry: false,
  });
  const manage = permissions.data?.canManage === true && !permissions.error;
  const tasks = useTaskReferences(client, item.id);
  const materials = useMaterialReferences(client, item.id);
  const nothingLinked =
    tasks.data?.items.length === 0 && materials.data?.items.length === 0;
  const contact = [item.email, item.phone].filter(Boolean).join(" · ");

  return (
    <div className="inbox-detail" data-testid="inbox-case-detail">
      {item.status !== "closed" ? (
        <NextStep
          action={
            <Button
              data-testid="close-case"
              onClick={() => onClose(item)}
              variant="primary"
            >
              Abschließen …
            </Button>
          }
          alternatives={
            item.status === "new" ? (
              <Button
                loading={takingOver}
                onClick={() => onTakeOver(item)}
                variant="secondary"
              >
                Übernehmen
              </Button>
            ) : null
          }
          consequence={
            item.contactStatus === "linked"
              ? "Antworten und danach mit Abschlussnotiz schließen."
              : "Kontakt zuordnen, dann antworten."
          }
        />
      ) : null}

      <DetailSection title="Anfrage">
        <blockquote className="case-message">
          <p className="case-subject">{item.subject}</p>
          <p className="case-body">{item.message}</p>
        </blockquote>
        <DetailProps
          items={[
            { label: "Von", value: fullName(item) },
            ...(contact
              ? [
                  {
                    label: "Kontakt",
                    value: <span className="wrap-anywhere">{contact}</span>,
                  },
                ]
              : []),
            { label: "Aktion", value: actionName },
            {
              label: "Eingegangen",
              value: (
                <time className="num" dateTime={item.receivedAt}>
                  {receivedLabel(item.receivedAt)}
                </time>
              ),
            },
            {
              label: "Referenz",
              value: <span className="mono">{item.publicReference}</span>,
            },
          ]}
        />
        <p className="case-privacy small subtle">
          <ShieldCheck aria-hidden="true" size={13} />
          <span>
            Gesendet über das öffentliche Formular mit Einwilligung (Zweck,
            Speicherung, Löschung). Die Person kennt die Referenznummer.
          </span>
        </p>
      </DetailSection>

      <DetailSection title="Kontakt in Twenty">
        <InboxContact
          address={address}
          client={client}
          item={item}
          manage={manage}
        />
      </DetailSection>

      <DetailSection title="Interne Notizen">
        <InboxComments address={address} client={client} item={item} />
      </DetailSection>

      <DetailSection title="Verknüpft">
        <div className="case-links">
          {nothingLinked ? (
            <span className="small subtle">Nichts verknüpft.</span>
          ) : null}
          <span aria-hidden="true" className="case-links-break" />
          <InboxTasks
            address={address}
            client={client}
            item={item}
            taskBasePath={taskBasePath}
          />
          <InboxMaterials address={address} client={client} item={item} />
        </div>
      </DetailSection>
    </div>
  );
}

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  CircleDot,
  Contact,
  Flag,
  Inbox as InboxIcon,
  UserRound,
} from "lucide-react";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";

import {
  ApiError,
  type Case,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Avatar,
  HotkeyProvider,
  ListView,
  StatusIcon,
  StatusLabel,
  StatusMessage,
  ToastProvider,
  useOptionalHotkeyRegistry,
  useOptionalToast,
  type ListColumns,
  type ListEditOutcome,
  type ListProperty,
  type ListSort,
  type ListViewDefinition,
} from "@leonaid/ui";

import { useContextCommands } from "../command-palette/store";
import type { ModulePageContext, ModuleSurface } from "../modules";
import { CaseDetail } from "./case-detail";
import { CloseCaseDialog, useCaseUpdates } from "./case-editor";
import { ContactStateLabel } from "./contact";
import "./inbox.css";
import {
  actionKey,
  CASE_STATUSES,
  caseStatusLabels,
  CASES_KEY,
  CONTACT_STATES,
  contactStateLabels,
  fullName,
  loadAllCases,
  managesCase,
  migrateCasePath,
  NONE,
  requestedCaseId,
  shortDay,
  shortReference,
  type Address,
} from "./inbox-model";

export interface InboxPageProps extends ModulePageContext {
  readonly basePath: string;
  /** Old case path `<base>/<id>`: opens that case in the pane. */
  readonly caseId?: string;
  readonly surface?: ModuleSurface;
}

/**
 * The inbox ("Eingang") on the list view, in the admin web and the PWA.
 * The PWA shell has no hotkey or toast provider yet; the page brings its
 * own then, so the list keys and the edit toasts work there too.
 */
export function InboxPage(props: InboxPageProps) {
  useState(() => {
    if (props.caseId) migrateCasePath(props.basePath, props.caseId);
    return null;
  });
  const registry = useOptionalHotkeyRegistry();
  const toast = useOptionalToast();
  let page: ReactNode = <InboxList {...props} />;
  if (!toast) page = <ToastProvider>{page}</ToastProvider>;
  if (!registry) page = <HotkeyProvider>{page}</HotkeyProvider>;
  return page;
}

const PAGE_SIZE = 100;

/** Every person eligible for cases of one action (server paging). */
async function loadAssignees(client: LeonAidApiClient, caseId: string) {
  const people: { userId: string; displayName: string }[] = [];
  let offset = 0;
  for (;;) {
    const page = await client.listInboxAssignees(caseId, {
      offset,
      limit: PAGE_SIZE,
    });
    people.push(...page.items);
    if (page.nextOffset == null) return people;
    offset = page.nextOffset;
  }
}

/** Names of the actions the account can see (for the "Aktion" property). */
async function loadActionNames(client: LeonAidApiClient) {
  const names = new Map<string, string>();
  let offset = 0;
  for (;;) {
    const page = await client.listTaskActionContexts({
      offset,
      limit: PAGE_SIZE,
    });
    for (const action of page.items) names.set(action.actionId, action.name);
    if (page.nextOffset == null) return names;
    offset = page.nextOffset;
  }
}

function useActionNames(
  client: LeonAidApiClient,
  identity: CurrentIdentityResponse,
) {
  const contexts = useQuery({
    queryKey: ["inbox-action-names"],
    queryFn: () => loadActionNames(client),
    retry: false,
    staleTime: 5 * 60_000,
  });
  return useMemo(() => {
    const names = new Map<string, string>();
    for (const membership of identity.actionMemberships)
      names.set(membership.actionId, membership.actionName);
    for (const [id, name] of contexts.data ?? []) names.set(id, name);
    return names;
  }, [contexts.data, identity.actionMemberships]);
}

function InboxList({
  basePath,
  client,
  identity,
  surface = "web",
}: InboxPageProps) {
  const address: Address = surface === "pwa" ? "du" : "Sie";
  const toast = useOptionalToast();
  const update = useCaseUpdates(client);
  const me = identity.userId;

  const cases = useQuery({
    queryKey: CASES_KEY,
    queryFn: ({ signal }) => loadAllCases(client, signal),
    retry: false,
  });
  // A deep link to a case the list does not hold (beyond the server's paging
  // limit, or not accessible): ask for that case alone.
  const [requested] = useState(requestedCaseId);
  const listed = cases.data?.items;
  const missing =
    requested !== null &&
    listed !== undefined &&
    !listed.some((item) => item.id === requested);
  const single = useQuery({
    queryKey: ["inbox-case", requested],
    queryFn: () => client.getInboxCase(requested!),
    enabled: missing,
    retry: false,
  });
  const rows = useMemo(() => {
    const items = listed ?? [];
    return missing && single.data ? [...items, single.data] : items;
  }, [listed, missing, single.data]);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const casesFor = useCallback((ids: readonly string[]) => {
    const byId = new Map(rowsRef.current.map((item) => [item.id, item]));
    return ids.flatMap((id) => {
      const item = byId.get(id);
      return item ? [item] : [];
    });
  }, []);

  const actionNames = useActionNames(client, identity);
  const actionName = useCallback(
    (item: Pick<Case, "actionId">) =>
      item.actionId === null
        ? "Allgemeine Anfrage"
        : (actionNames.get(item.actionId) ?? "Charity-Aktion"),
    [actionNames],
  );

  /* ----- assignees: eligible people per action, loaded for managed cases ----- */
  const managedActions = useMemo(() => {
    const first = new Map<string, string>();
    for (const item of rows) {
      const key = actionKey(item);
      if (!first.has(key) && managesCase(identity, item))
        first.set(key, item.id);
    }
    return [...first.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [identity, rows]);
  const assigneeQueries = useQueries({
    queries: managedActions.map(([key, caseId]) => ({
      queryKey: ["inbox-assignees", "all", key],
      queryFn: () => loadAssignees(client, caseId),
      retry: false,
      staleTime: 60_000,
    })),
  });
  const assigneesPending = assigneeQueries.some((query) => query.isPending);
  const assigneeData = assigneeQueries.map((query) => query.data);
  const assigneeSignature = JSON.stringify([
    managedActions.map(([key]) => key),
    assigneeData.map(
      (people) => people?.map((person) => person.userId) ?? null,
    ),
  ]);
  const { eligible, names } = useMemo(() => {
    const eligibleByAction = new Map<string, Set<string>>();
    const nameById = new Map<string, string>([[me, identity.displayName]]);
    managedActions.forEach(([key], index) => {
      const people = assigneeData[index];
      if (!people) return;
      eligibleByAction.set(key, new Set(people.map((person) => person.userId)));
      for (const person of people)
        nameById.set(person.userId, person.displayName);
    });
    return { eligible: eligibleByAction, names: nameById };
    // assigneeData is a new array each render; the signature tracks content.
  }, [assigneeSignature, identity.displayName, me]);
  const nameOf = useCallback(
    (userId: string) => names.get(userId) ?? "Unbekannte Person",
    [names],
  );

  /* ----- closing with a note ----- */
  const [closing, setClosing] = useState<{
    readonly ids: readonly string[];
    readonly resolve: (outcome: ListEditOutcome) => void;
  } | null>(null);
  const closingOpen = useRef(false);
  const requestClose = useCallback((ids: readonly string[]) => {
    // One closing dialog at a time; a second request backs out at once.
    if (closingOpen.current)
      return Promise.resolve<ListEditOutcome>("cancelled");
    closingOpen.current = true;
    return new Promise<ListEditOutcome>((resolve) =>
      setClosing({ ids, resolve }),
    );
  }, []);
  const finishClosing = (outcome: ListEditOutcome) => {
    closingOpen.current = false;
    closing?.resolve(outcome);
    setClosing(null);
  };
  const [takingOver, setTakingOver] = useState<string | null>(null);

  const anyManaged = managedActions.length > 0;
  const properties = useMemo<ListProperty<Case>[]>(() => {
    const assignedIds = [
      ...new Set(
        rows.flatMap((item) =>
          item.assigneeUserId && item.assigneeUserId !== me
            ? [item.assigneeUserId]
            : [],
        ),
      ),
    ];
    const others = [...new Set([...names.keys(), ...assignedIds])]
      .filter((id) => id !== me)
      .sort((a, b) => nameOf(a).localeCompare(nameOf(b), "de"));
    const assigneeOptions = [me, ...others].map((id) => ({
      value: id,
      label: nameOf(id),
      icon: <Avatar name={nameOf(id)} size="xs" />,
    }));
    const actionKeys = [...new Set(rows.map(actionKey))].sort((a, b) =>
      a === NONE
        ? 1
        : b === NONE
          ? -1
          : actionName({ actionId: a }).localeCompare(
              actionName({ actionId: b }),
              "de",
            ),
    );
    return [
      {
        id: "status",
        label: "Status",
        icon: CircleDot,
        get: (row) => row.status,
        options: CASE_STATUSES.map((value) => ({
          value,
          label: caseStatusLabels[value],
          icon: (
            <StatusIcon
              label={caseStatusLabels[value]}
              status={
                value === "new"
                  ? "open"
                  : value === "in_progress"
                    ? "progress"
                    : "done"
              }
            />
          ),
        })),
        // Everyone who reads a case may change its status; closing asks for
        // the note first. The server checks again.
        edit: {
          key: "s",
          apply: async (ids, value) => {
            const status = value as Case["status"];
            const targets = casesFor(ids).filter(
              (item) => item.status !== status,
            );
            if (targets.length === 0) return;
            if (status === "closed")
              return requestClose(targets.map((item) => item.id));
            await update(targets, { status });
          },
        },
        chip: (row) => <StatusLabel status={caseStatusLabels[row.status]} />,
      },
      {
        id: "contact",
        label: "Kontakt",
        icon: Contact,
        get: (row) => row.contactStatus,
        // Read-only: the contact changes only through the Twenty matching.
        options: CONTACT_STATES.map((value) => ({
          value,
          label: contactStateLabels[value].short,
          icon: (
            <StatusIcon
              label={contactStateLabels[value].short}
              status={contactStateLabels[value].shape}
            />
          ),
        })),
        chip: (row) => <ContactStateLabel short state={row.contactStatus} />,
      },
      {
        id: "assignee",
        label: "Zuständigkeit",
        icon: UserRound,
        get: (row) => row.assigneeUserId ?? NONE,
        options: [...assigneeOptions, { value: NONE, label: "Niemand" }],
        optionsPending: assigneesPending,
        // Only the case management assigns; offered only where this account
        // manages every target case. The server checks again.
        edit: anyManaged
          ? {
              key: "a",
              options: (targets) => {
                const sets: Set<string>[] = [];
                for (const item of targets) {
                  if (!managesCase(identity, item)) return [];
                  const people = eligible.get(actionKey(item));
                  if (!people) return [];
                  sets.push(people);
                }
                if (sets.length === 0) return [];
                // Only people eligible for every target case.
                return [
                  ...assigneeOptions.filter((option) =>
                    sets.every((people) => people.has(option.value)),
                  ),
                  { value: NONE, label: "Niemand" },
                ];
              },
              apply: async (ids, value) => {
                const assigneeUserId = value === NONE ? null : value;
                const targets = casesFor(ids).filter(
                  (item) => item.assigneeUserId !== assigneeUserId,
                );
                if (targets.length) await update(targets, { assigneeUserId });
              },
            }
          : undefined,
        chip: (row) =>
          row.assigneeUserId ? (
            <>
              <Avatar
                label={`Zuständig: ${nameOf(row.assigneeUserId)}`}
                name={nameOf(row.assigneeUserId)}
                size="xs"
              />
              <span className="chip-name">{nameOf(row.assigneeUserId)}</span>
            </>
          ) : (
            <span
              aria-label="Niemand zuständig"
              className="avatar-empty"
              role="img"
            />
          ),
      },
      {
        id: "campaign",
        label: "Aktion",
        icon: Flag,
        get: actionKey,
        options: actionKeys.map((key) => ({
          value: key,
          label: key === NONE ? "Allgemein" : actionName({ actionId: key }),
        })),
      },
    ];
  }, [
    actionName,
    anyManaged,
    assigneesPending,
    casesFor,
    eligible,
    identity,
    me,
    nameOf,
    names,
    requestClose,
    rows,
    update,
  ]);

  const sorts = useMemo<ListSort<Case>[]>(
    () => [
      {
        id: "new",
        label: "Neueste zuerst",
        compare: (a, b) => b.receivedAt.localeCompare(a.receivedAt),
      },
      {
        id: "old",
        label: "Älteste zuerst",
        compare: (a, b) => a.receivedAt.localeCompare(b.receivedAt),
      },
    ],
    [],
  );

  const views = useMemo<ListViewDefinition[]>(
    () => [
      {
        id: "open",
        label: "Offen",
        filters: [{ prop: "status", values: ["new", "in_progress"] }],
        groupBy: "status",
        sort: "new",
      },
      {
        id: "mine",
        label: "Mir zugewiesen",
        filters: [{ prop: "assignee", values: [me] }],
        groupBy: null,
        sort: "new",
      },
      {
        id: "contact",
        label: "Kontakt klären",
        filters: [{ prop: "contact", values: ["needs_review", "failed"] }],
        groupBy: null,
        sort: "old",
      },
      { id: "all", label: "Alle", filters: [], groupBy: null, sort: "new" },
    ],
    [me],
  );

  const columns = useMemo<ListColumns<Case>>(
    () => ({
      primary: (row) => (
        <span data-inbox-row={row.id}>
          <span className="mono order-no">
            {shortReference(row.publicReference)}
          </span>{" "}
          {row.subject}
        </span>
      ),
      secondary: (row) =>
        row.actionId === null
          ? fullName(row)
          : `${fullName(row)} · ${actionName(row)}`,
      trailing: (row) => (
        <time dateTime={row.receivedAt}>{shortDay(row.receivedAt)}</time>
      ),
    }),
    [actionName],
  );

  const getId = useCallback((row: Case) => row.id, []);
  const searchText = useCallback(
    (row: Case) =>
      `${row.publicReference} ${row.subject} ${row.message} ${fullName(row)} ${row.email ?? ""} ${row.phone ?? ""}`,
    [],
  );
  const detailTitle = useCallback((row: Case) => row.subject, []);

  const takeOver = async (item: Case) => {
    setTakingOver(item.id);
    try {
      await update([item], {
        status: "in_progress",
        assigneeUserId:
          item.assigneeUserId ?? (managesCase(identity, item) ? me : null),
      });
      toast?.show({ title: "Anfrage übernommen.", tone: "success" });
    } catch {
      toast?.show({
        title: "Die Anfrage wurde nicht übernommen.",
        description:
          address === "Sie"
            ? "Bitte versuchen Sie es erneut."
            : "Bitte versuche es erneut.",
        tone: "error",
      });
    } finally {
      setTakingOver(null);
    }
  };

  const status = cases.isPending
    ? "loading"
    : cases.isError
      ? "error"
      : "ready";
  const closingCases = closing ? casesFor(closing.ids) : null;

  return (
    <div className="inbox-page" data-zone="inbox">
      <ListView<Case>
        beforeList={
          <>
            {cases.error instanceof ApiError && cases.error.status === 401 ? (
              <StatusMessage className="inbox-callout" tone="error">
                {address === "Sie"
                  ? "Bitte melden Sie sich erneut an."
                  : "Bitte melde dich erneut an."}
              </StatusMessage>
            ) : null}
            {missing && single.isError ? (
              <StatusMessage
                className="inbox-callout"
                id="inbox-case-unavailable"
                tone="error"
              >
                {address === "Sie"
                  ? "Dieser Eingang ist nicht mehr verfügbar oder Sie haben keinen Zugriff."
                  : "Dieser Eingang ist nicht mehr verfügbar oder du hast keinen Zugriff."}
              </StatusMessage>
            ) : null}
            {cases.data?.truncated ? (
              <StatusMessage className="inbox-callout" tone="info">
                Es werden die neuesten {cases.data.items.length} Anfragen
                gezeigt. Ältere Anfragen öffnen Sie über die Suche.
              </StatusMessage>
            ) : null}
          </>
        }
        className="inbox-list"
        columns={columns}
        detailTitle={detailTitle}
        emptyIcon={InboxIcon}
        entityLabel={{ one: "Anfrage", many: "Anfragen" }}
        getId={getId}
        id="inbox"
        onRetry={() => void cases.refetch()}
        properties={properties}
        renderDetail={(row) => (
          <CaseDetail
            actionName={actionName(row)}
            address={address}
            client={client}
            item={row}
            key={row.id}
            onClose={(item) => {
              void requestClose([item.id]).then((outcome) => {
                if (outcome !== "cancelled")
                  toast?.show({
                    title: `${shortReference(item.publicReference)} abgeschlossen.`,
                    tone: "success",
                  });
              });
            }}
            onTakeOver={(item) => void takeOver(item)}
            takingOver={takingOver === row.id}
            taskBasePath={basePath.replace(/\/inbox$/, "/tasks")}
          />
        )}
        rows={rows}
        searchText={searchText}
        sorts={sorts}
        status={status}
        title="Eingang"
        useCommands={useContextCommands}
        views={views}
      />
      <CloseCaseDialog
        address={address}
        cases={closingCases}
        client={client}
        onCancel={() => finishClosing("cancelled")}
        onDone={() => finishClosing(undefined)}
      />
    </div>
  );
}

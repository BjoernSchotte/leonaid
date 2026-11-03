import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { useOptionalToast } from "@leonaid/ui";

import { says, type Address } from "./task-copy";
import { localIsoDate } from "./task-model";

const LAST_LIST_KEY = "leonaid.tasks.quick-list";

function readLastList(): string | null {
  try {
    return window.localStorage.getItem(LAST_LIST_KEY);
  } catch {
    return null;
  }
}

function writeLastList(listId: string) {
  try {
    window.localStorage.setItem(LAST_LIST_KEY, listId);
  } catch {
    // Remembering the list is a convenience only.
  }
}

export interface QuickAddList {
  readonly id: string;
  readonly title: string;
}

/** Whether I may be assigned in this list (people with write access). */
export function useSelfAssignable(
  client: LeonAidApiClient,
  identity: CurrentIdentityResponse,
  listId: string,
): boolean | undefined {
  const all = useQuery({
    queryKey: ["task-assignees", listId, "all"],
    queryFn: () => client.listTaskAssignees(listId, { limit: 100 }),
    enabled: !!listId,
    retry: false,
    staleTime: 300_000,
  });
  const inFirstPage = all.data?.items.some(
    (person) => person.userId === identity.userId,
  );
  const searchNeeded =
    !!all.data && !inFirstPage && all.data.nextOffset !== null;
  const searched = useQuery({
    queryKey: ["task-assignees", listId, "self", identity.displayName],
    queryFn: () =>
      client.listTaskAssignees(listId, {
        search: identity.displayName,
        limit: 100,
      }),
    enabled: searchNeeded,
    retry: false,
  });
  if (!listId) return undefined;
  // Without the check the task stays unassigned rather than blocked.
  if (all.isError) return false;
  if (!all.data) return undefined;
  if (inFirstPage) return true;
  if (!searchNeeded || searched.isError) return false;
  return searched.data?.items.some(
    (person) => person.userId === identity.userId,
  );
}

/**
 * The prototype's quick add: one field in the page header, Enter creates,
 * Esc closes. Without a fixed list (all tasks) a list picker joins it.
 */
export function TaskQuickAdd({
  address,
  assignSelf,
  client,
  defaultListId,
  fixedList,
  identity,
  lists,
  onClose,
  onNeedList,
  planToday,
}: {
  readonly address: Address;
  /** The view shows my tasks: assign the new one to me when allowed. */
  readonly assignSelf: boolean;
  readonly client: LeonAidApiClient;
  /** A list the current filter names. */
  readonly defaultListId: string | null;
  /** The list page's own list. */
  readonly fixedList: QuickAddList | null;
  readonly identity: CurrentIdentityResponse;
  /** Lists I may add to. */
  readonly lists: readonly QuickAddList[];
  readonly onClose: () => void;
  /** No list to add to yet: show where to create one. */
  readonly onNeedList: () => void;
  /** "Mein Plan": plan the new task for today. */
  readonly planToday: boolean;
}) {
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const input = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLSelectElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const operation = useRef(crypto.randomUUID());
  const [title, setTitle] = useState("");
  const [listChoice, setListChoice] = useState(() => {
    if (fixedList) return fixedList.id;
    const known = (id: string | null) =>
      !!id && lists.some((list) => list.id === id);
    if (known(defaultListId)) return defaultListId!;
    const last = readLastList();
    if (known(last)) return last!;
    return lists.length === 1 ? lists[0]!.id : "";
  });
  // Lists load after the form opens: take the only one once it is there.
  useEffect(() => {
    if (!fixedList && !listChoice && lists.length === 1) {
      setListChoice(lists[0]!.id);
    }
  }, [fixedList, listChoice, lists]);
  useEffect(() => {
    input.current?.focus();
  }, []);
  const selfAssignable = useSelfAssignable(client, identity, listChoice);
  const create = useMutation({
    mutationFn: async (value: string) => {
      const created = await client.createTask(listChoice, {
        title: value,
        description: "",
        assigneeUserId: assignSelf && selfAssignable ? identity.userId : null,
        epicId: null,
        dueAt: null,
        deferredUntil: null,
        idempotencyKey: operation.current,
      });
      if (planToday) {
        try {
          await client.setTaskPlan(created.id, {
            idempotencyKey: crypto.randomUUID(),
            expectedRevision: 0,
            state: "scheduled",
            plannedOn: localIsoDate(),
          });
          return { created, planned: true };
        } catch {
          return { created, planned: false };
        }
      }
      return { created, planned: false };
    },
    onSuccess: async ({ created, planned }) => {
      operation.current = crypto.randomUUID();
      setTitle("");
      if (!fixedList) writeLastList(listChoice);
      toast?.show({
        title: planned
          ? `Aufgabe „${created.title}“ angelegt – im Plan unter Heute.`
          : `Aufgabe „${created.title}“ angelegt.`,
        tone: "success",
      });
      await cache.invalidateQueries({ queryKey: ["tasks"] });
      input.current?.focus();
    },
    onError: () =>
      toast?.show({
        title: "Die Aufgabe konnte nicht angelegt werden.",
        description: "Der Titel bleibt erhalten.",
        tone: "error",
      }),
  });
  const close = () => {
    setTitle("");
    onClose();
  };
  return (
    <form
      aria-label="Aufgabe schnell erfassen"
      className="quick-add"
      data-list-scope={fixedList ? "current" : "select"}
      onSubmit={(event) => {
        event.preventDefault();
        const value = title.trim();
        if (!value || create.isPending) return;
        if (!listChoice && lists.length === 0) {
          toast?.show({
            title: says(
              address,
              "Lege zuerst eine Liste an.",
              "Legen Sie zuerst eine Liste an.",
            ),
            tone: "info",
          });
          onNeedList();
          return;
        }
        if (!listChoice) {
          toast?.show({
            title: says(
              address,
              "Wähle zuerst eine Liste.",
              "Wählen Sie zuerst eine Liste.",
            ),
            tone: "info",
          });
          picker.current?.focus();
          return;
        }
        // Wait for the assignment check so "Für mich" lands with me.
        if (assignSelf && selfAssignable === undefined) return;
        create.mutate(value);
      }}
      onBlur={(event) => {
        // Close when an empty form loses focus to another control, as in
        // the prototype. Focus moved by the page (a landmark, a heading with
        // tabindex -1) or a click on empty space keeps it open.
        const next = event.relatedTarget;
        if (!(next instanceof HTMLElement)) return;
        if (form.current?.contains(next)) return;
        if (next.getAttribute("tabindex") === "-1") return;
        if (!title.trim() && !create.isPending) close();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopPropagation();
        close();
      }}
      ref={form}
    >
      <label className="sr-only" htmlFor="quick-add-input">
        Titel
      </label>
      <ListChecks aria-hidden="true" size={15} />
      <input
        aria-busy={create.isPending || undefined}
        className="quick-add-input"
        id="quick-add-input"
        maxLength={240}
        onChange={(event) => {
          setTitle(event.target.value);
          operation.current = crypto.randomUUID();
          create.reset();
        }}
        placeholder="Neue Aufgabe – Enter legt an, Esc bricht ab"
        readOnly={create.isPending}
        ref={input}
        value={title}
      />
      {fixedList ? null : (
        <>
          <label className="sr-only" htmlFor="quick-add-list">
            Aufgabenliste
          </label>
          <select
            className="quick-add-list"
            id="quick-add-list"
            onChange={(event) => {
              setListChoice(event.target.value);
              operation.current = crypto.randomUUID();
              create.reset();
            }}
            ref={picker}
            value={listChoice}
          >
            <option value="">Liste wählen …</option>
            {lists.map((list) => (
              <option key={list.id} value={list.id}>
                {list.title}
              </option>
            ))}
          </select>
        </>
      )}
    </form>
  );
}

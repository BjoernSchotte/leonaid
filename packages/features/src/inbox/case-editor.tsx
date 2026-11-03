import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import {
  ApiError,
  type Case,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { Button, Field, Modal, StatusMessage, Textarea } from "@leonaid/ui";

import {
  acceptCases,
  CASES_KEY,
  MIN_CLOSURE_NOTE,
  shortReference,
  type Address,
} from "./inbox-model";

export interface CaseChange {
  readonly status?: Case["status"];
  readonly assigneeUserId?: string | null;
  /** Required when the status becomes closed. */
  readonly closureNote?: string;
}

/** Some of the cases were not saved; `firstError` is the first server error. */
export class CaseUpdateError extends Error {
  constructor(
    readonly failed: number,
    readonly total: number,
    readonly firstError: unknown,
  ) {
    super(`${failed} of ${total} inbox cases were not updated`);
  }
}

function updateBody(item: Case, change: CaseChange) {
  const status = change.status ?? item.status;
  return {
    // One key per attempt; the expected revision stops a double apply.
    idempotencyKey: crypto.randomUUID(),
    expectedRevision: item.revision,
    status,
    assigneeUserId:
      change.assigneeUserId !== undefined
        ? change.assigneeUserId
        : item.assigneeUserId,
    closureNote:
      status === "closed"
        ? (change.closureNote ?? item.closureNote ?? "").trim()
        : null,
  };
}

/**
 * Saves one change on several cases (`PUT /inbox-cases/{id}` each, with its
 * own revision). Saved cases land in the cache even when others fail; then
 * the whole batch rejects with a {@link CaseUpdateError}.
 */
export function useCaseUpdates(client: LeonAidApiClient) {
  const cache = useQueryClient();
  return useCallback(
    async (cases: readonly Case[], change: CaseChange) => {
      const results = await Promise.allSettled(
        cases.map((item) =>
          client.updateInboxCase(item.id, updateBody(item, change)),
        ),
      );
      const saved = results.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : [],
      );
      acceptCases(cache, saved);
      const failures = results.flatMap((result) =>
        result.status === "rejected" ? [result.reason as unknown] : [],
      );
      if (failures.length > 0) {
        void cache.invalidateQueries({ queryKey: CASES_KEY });
        throw new CaseUpdateError(failures.length, cases.length, failures[0]);
      }
      return saved;
    },
    [cache, client],
  );
}

function closeError(error: unknown, address: Address): string {
  const cause = error instanceof CaseUpdateError ? error.firstError : error;
  const partial =
    error instanceof CaseUpdateError && error.total > 1
      ? `${error.failed} von ${error.total} Anfragen wurden nicht abgeschlossen. `
      : "";
  if (cause instanceof ApiError && cause.status === 409)
    return `${partial}Die Anfrage wurde inzwischen geändert. Der aktuelle Stand wird geladen; die Notiz bleibt erhalten.`;
  return `${partial}Die Anfrage konnte nicht abgeschlossen werden. Die Notiz bleibt erhalten. ${
    address === "Sie"
      ? "Prüfen Sie Ihren Zugriff und versuchen Sie es erneut."
      : "Prüfe deinen Zugriff und versuche es erneut."
  }`;
}

export interface CloseCaseDialogProps {
  readonly client: LeonAidApiClient;
  readonly address: Address;
  /** The cases to close, read fresh on every render; null keeps it shut. */
  readonly cases: readonly Case[] | null;
  readonly onDone: (closed: readonly Case[]) => void;
  readonly onCancel: () => void;
}

/** "Anfrage abschließen": closing always records an internal note. */
export function CloseCaseDialog(props: CloseCaseDialogProps) {
  // A fresh form per opening: the key resets the note and errors.
  return props.cases?.length ? (
    <CloseCaseForm
      key={props.cases.map((item) => item.id).join(",")}
      {...props}
      cases={props.cases}
    />
  ) : null;
}

function CloseCaseForm({
  address,
  cases,
  client,
  onCancel,
  onDone,
}: CloseCaseDialogProps & { readonly cases: readonly Case[] }) {
  const update = useCaseUpdates(client);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string>();
  const [serverError, setServerError] = useState<string>();
  const [pending, setPending] = useState(false);
  const first = cases[0]!;
  const fieldId = `close-note-${first.id}`;

  async function submit() {
    if (pending) return;
    setServerError(undefined);
    if (note.trim().length < MIN_CLOSURE_NOTE) {
      setError(
        `Bitte kurz festhalten, was erledigt wurde (mindestens ${MIN_CLOSURE_NOTE} Zeichen). Die Notiz bleibt intern.`,
      );
      return;
    }
    // Cases a previous, partly failed attempt already closed stay closed.
    const open = cases.filter((item) => item.status !== "closed");
    setPending(true);
    try {
      const closed = await update(open, {
        status: "closed",
        closureNote: note.trim(),
      });
      onDone(closed);
    } catch (cause) {
      setServerError(closeError(cause, address));
      setPending(false);
    }
  }

  return (
    <Modal
      className="inbox-dialog"
      description={
        cases.length === 1
          ? `${shortReference(first.publicReference)} · ${first.subject}`
          : `${cases.length} Anfragen`
      }
      footer={
        <>
          <Button disabled={pending} onClick={onCancel} variant="ghost">
            Abbrechen
          </Button>
          <Button
            data-testid="close-case-submit"
            form="close-case-form"
            loading={pending}
            type="submit"
            variant="primary"
          >
            Abschließen
          </Button>
        </>
      }
      onClose={() => {
        if (!pending) onCancel();
      }}
      open
      title={
        cases.length === 1
          ? "Anfrage abschließen"
          : `${cases.length} Anfragen abschließen`
      }
    >
      <form
        className="stack"
        id="close-case-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <Field
          error={error}
          hint="Pflichtfeld. Nur für das Team sichtbar. Der Abschluss ist keine Förderzusage oder Auszahlung."
          id={fieldId}
          label="Abschlussnotiz"
        >
          <Textarea
            autoFocus
            data-testid="close-case-note"
            disabled={pending}
            maxLength={4000}
            onChange={(event) => {
              setNote(event.target.value);
              setError(undefined);
            }}
            value={note}
          />
        </Field>
        {serverError ? (
          <StatusMessage tone="error">{serverError}</StatusMessage>
        ) : null}
      </form>
    </Modal>
  );
}

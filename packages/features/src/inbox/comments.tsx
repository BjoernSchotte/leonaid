import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { Lock, RefreshCw } from "lucide-react";
import { useRef, useState } from "react";

import type { Case, LeonAidApiClient } from "@leonaid/api-client";
import { Button, Icon, Input, StatusMessage } from "@leonaid/ui";

import type { Address } from "./inbox-model";

const PAGE = 25;
const dateTime = (value: string) =>
  new Date(value).toLocaleString("de-DE", {
    dateStyle: "short",
    timeStyle: "short",
  });

/**
 * "Interne Notizen": oldest first, as in the prototype, so a new note lands
 * right above the input. Older pages load on request. The closing note of a
 * closed case is the last entry. No e-mail is sent.
 */
export function InboxComments({
  address,
  client,
  item,
}: {
  readonly address: Address;
  readonly client: LeonAidApiClient;
  readonly item: Case;
}) {
  const cache = useQueryClient();
  const [body, setBody] = useState("");
  const operation = useRef(crypto.randomUUID());
  const queryKey = ["inbox-comments", item.id];
  const comments = useInfiniteQuery({
    queryKey,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      client.listInboxComments(item.id, { offset: pageParam, limit: PAGE }),
    getNextPageParam: (page) => page.nextOffset ?? undefined,
    retry: false,
  });
  const add = useMutation({
    mutationFn: () =>
      client.addInboxComment(item.id, {
        body: body.trim(),
        idempotencyKey: operation.current,
      }),
    onSuccess: () => {
      setBody("");
      operation.current = crypto.randomUUID();
      void cache.invalidateQueries({ queryKey });
    },
  });
  // Offset pages overlap after a new note; keep each note once.
  const notes = [
    ...new Map(
      (comments.data?.pages ?? [])
        .flatMap((page) => page.items)
        .map((comment) => [comment.id, comment]),
    ).values(),
  ].reverse();
  return (
    <>
      {comments.isPending ? (
        <p className="small subtle" role="status">
          Notizen werden geladen …
        </p>
      ) : null}
      {comments.error ? (
        <StatusMessage tone="error">
          <p>Die Notizen konnten nicht geladen werden.</p>
          <Button
            icon={RefreshCw}
            onClick={() => void comments.refetch()}
            size="sm"
            variant="secondary"
          >
            Notizen erneut laden
          </Button>
        </StatusMessage>
      ) : null}
      {comments.hasNextPage ? (
        <Button
          className="case-older"
          loading={comments.isFetchingNextPage}
          onClick={() => void comments.fetchNextPage()}
          size="sm"
          variant="ghost"
        >
          Ältere Notizen laden
        </Button>
      ) : null}
      {comments.data && (notes.length > 0 || item.closureNote) ? (
        <ul className="case-notes" data-testid="inbox-notes">
          {notes.map((comment) => (
            <li key={comment.id}>
              <Icon icon={Lock} size={12} />
              <span className="case-note-text">{comment.body}</span>
              <time className="subtle" dateTime={comment.createdAt}>
                {dateTime(comment.createdAt)}
              </time>
            </li>
          ))}
          {item.closureNote ? (
            <li data-testid="inbox-closure-note">
              <Icon icon={Lock} size={12} />
              <span className="case-note-text">
                Abschlussnotiz: {item.closureNote}
              </span>
              {item.closedAt ? (
                <time className="subtle" dateTime={item.closedAt}>
                  {dateTime(item.closedAt)}
                </time>
              ) : null}
            </li>
          ) : null}
        </ul>
      ) : comments.data ? (
        <p className="small subtle case-gap-bottom">Noch keine Notizen.</p>
      ) : null}
      <form
        className="case-note-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!body.trim() || add.isPending) return;
          add.mutate();
        }}
      >
        <label className="sr-only" htmlFor={`note-${item.id}`}>
          Interne Notiz
        </label>
        <Input
          disabled={add.isPending}
          id={`note-${item.id}`}
          maxLength={4000}
          onChange={(event) => {
            setBody(event.target.value);
            operation.current = crypto.randomUUID();
            add.reset();
          }}
          placeholder="Notiz für das Team …"
          value={body}
        />
        <Button
          disabled={!body.trim()}
          loading={add.isPending}
          size="sm"
          type="submit"
        >
          Hinzufügen
        </Button>
      </form>
      {add.error ? (
        <StatusMessage tone="error">
          {address === "Sie"
            ? "Die Notiz konnte nicht gespeichert werden. Ihr Text bleibt erhalten; prüfen Sie Ihren Zugriff und versuchen Sie es erneut."
            : "Die Notiz konnte nicht gespeichert werden. Dein Text bleibt erhalten; prüfe deinen Zugriff und versuche es erneut."}
        </StatusMessage>
      ) : null}
    </>
  );
}

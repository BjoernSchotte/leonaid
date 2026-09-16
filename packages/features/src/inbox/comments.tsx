import {
  ArrowLeft01Icon,
  ArrowRight01Icon,
  FloppyDiskIcon,
  RefreshIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button, StatusMessage } from "@leonaid/ui";
import type { LeonAidApiClient } from "@leonaid/api-client";

export function InboxComments({
  client,
  caseId,
}: {
  client: LeonAidApiClient;
  caseId: string;
}) {
  const cache = useQueryClient();
  const [body, setBody] = useState("");
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState("");
  const operation = useRef(crypto.randomUUID());
  const comments = useQuery({
    queryKey: ["inbox-comments", caseId, offset],
    queryFn: () => client.listInboxComments(caseId, { offset, limit: 25 }),
    retry: false,
  });
  const add = useMutation({
    mutationFn: () =>
      client.addInboxComment(caseId, {
        body: body.trim(),
        idempotencyKey: operation.current,
      }),
    onSuccess: () => {
      setBody("");
      setOffset(0);
      operation.current = crypto.randomUUID();
      setNotice("Interne Notiz gespeichert.");
      void cache.invalidateQueries({ queryKey: ["inbox-comments", caseId] });
    },
  });
  return (
    <section aria-labelledby="inbox-comments-heading">
      <h2 id="inbox-comments-heading">Interne Notizen</h2>
      <p>
        Nur für Personen mit Zugriff auf diesen Eingang. Es wird keine E-Mail
        versendet.
      </p>
      <form
        className="inbox-form"
        onSubmit={(event) => {
          event.preventDefault();
          setNotice("");
          add.mutate();
        }}
      >
        <label>
          Neue Notiz
          <textarea
            required
            maxLength={4000}
            rows={4}
            value={body}
            disabled={add.isPending}
            onChange={(event) => {
              setBody(event.target.value);
              operation.current = crypto.randomUUID();
              add.reset();
              setNotice("");
            }}
          />
        </label>
        <Button
          icon={
            <HugeiconsIcon
              icon={FloppyDiskIcon}
              size={16}
              strokeWidth={1.7}
              aria-hidden="true"
            />
          }
          variant="primary"
          type="submit"
          disabled={add.isPending || !body.trim()}
        >
          {add.isPending ? "Wird gespeichert …" : "Notiz speichern"}
        </Button>
        {add.error && (
          <StatusMessage tone="error">
            <p>
              Die Notiz konnte nicht gespeichert werden. Dein Text bleibt
              erhalten; prüfe deinen Zugriff und versuche es erneut.
            </p>
          </StatusMessage>
        )}
        {notice && <p role="status">{notice}</p>}
      </form>
      {comments.isPending && <p role="status">Notizen werden geladen …</p>}
      {comments.error && (
        <StatusMessage tone="error">
          <p>Die Notizen konnten nicht geladen werden.</p>
          <Button
            icon={
              <HugeiconsIcon
                icon={RefreshIcon}
                size={16}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            }
            variant="secondary"
            onClick={() => void comments.refetch()}
          >
            Notizen erneut laden
          </Button>
        </StatusMessage>
      )}
      {!comments.error && comments.data && (
        <>
          {comments.data.items.length === 0 ? (
            <p>Noch keine internen Notizen.</p>
          ) : (
            <ol className="inbox-results">
              {comments.data.items.map((comment) => (
                <li key={comment.id}>
                  <time dateTime={comment.createdAt}>
                    {new Date(comment.createdAt).toLocaleString("de-DE")}
                  </time>
                  <p className="inbox-message">{comment.body}</p>
                </li>
              ))}
            </ol>
          )}
          <nav className="inbox-paging" aria-label="Notizenseiten">
            <Button
              icon={
                <HugeiconsIcon
                  icon={ArrowLeft01Icon}
                  size={16}
                  strokeWidth={1.7}
                  aria-hidden="true"
                />
              }
              variant="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              Neuere Notizen
            </Button>
            <Button
              icon={
                <HugeiconsIcon
                  icon={ArrowRight01Icon}
                  size={16}
                  strokeWidth={1.7}
                  aria-hidden="true"
                />
              }
              variant="secondary"
              disabled={comments.data.nextOffset == null}
              onClick={() => setOffset(comments.data.nextOffset ?? offset)}
            >
              Ältere Notizen
            </Button>
          </nav>
        </>
      )}
    </section>
  );
}

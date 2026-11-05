import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage, useLeaveGuard } from "@leonaid/ui";

import { says, type Address } from "./task-copy";
import type { Task } from "./task-editor";

/**
 * Priority and list tags (Schlagworte) of one task, saved together in one
 * task revision, separate from the main editor, so a conflict keeps the
 * draft of both forms. Steps live in the detail's "Schritte" section. Without a draft the form follows newer revisions of
 * `task`; with a draft it keeps the revision it started from, so a save
 * after someone else's change is refused instead of overwriting it.
 */
export function TaskStructurePanel({
  address = "du",
  client,
  task,
  onDirtyChange,
}: {
  address?: Address;
  client: LeonAidApiClient;
  task: Task;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const id = useId();
  const cache = useQueryClient();
  const operation = useRef(crypto.randomUUID());
  const tagOperation = useRef(crypto.randomUUID());
  const [base, setBase] = useState(task);
  const [priority, setPriority] = useState(task.priority);
  const [tagIds, setTagIds] = useState(task.tags.map((tag) => tag.id));
  const [newTag, setNewTag] = useState("");
  const tagKey = (value: Task) => value.tags.map((tag) => tag.id).join(" ");
  const dirty = priority !== base.priority || tagIds.join(" ") !== tagKey(base);
  useEffect(() => {
    if (dirty || task.revision === base.revision) return;
    setBase(task);
    setPriority(task.priority);
    setTagIds(task.tags.map((tag) => tag.id));
  }, [base.revision, dirty, task]);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  useLeaveGuard(dirty);
  const tags = useQuery({
    queryKey: ["task-tags", task.listId],
    queryFn: () => client.listTaskTags(task.listId, { limit: 100 }),
    retry: false,
  });
  const changed = () => {
    operation.current = crypto.randomUUID();
    save.reset();
  };
  const save = useMutation({
    mutationFn: () =>
      client.setTaskStructure(task.id, {
        idempotencyKey: operation.current,
        // Steps are ticked and edited in "Schritte" and saved at once; a
        // step change alone must not turn this save into a conflict. Only
        // a change to priority or tags since the form opened does.
        expectedRevision:
          task.priority === base.priority && tagKey(task) === tagKey(base)
            ? task.revision
            : base.revision,
        priority,
        tagIds,
        checklist: task.checklist,
      }),
    onSuccess: async (saved) => {
      operation.current = crypto.randomUUID();
      setBase(saved);
      onDirtyChange?.(false);
      await cache.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const createTag = useMutation({
    mutationFn: () =>
      client.createTaskTag(task.listId, {
        idempotencyKey: tagOperation.current,
        title: newTag.trim(),
      }),
    onSuccess: async (created) => {
      tagOperation.current = crypto.randomUUID();
      setNewTag("");
      setTagIds((current) => [...current, created.id]);
      changed();
      await cache.invalidateQueries({ queryKey: ["task-tags", task.listId] });
    },
  });
  return (
    <form
      className="task-form task-structure"
      aria-labelledby={`${id}-heading`}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h3 className="task-form-title" id={`${id}-heading`}>
        Priorität und Schlagworte
      </h3>
      <fieldset className="task-fields" disabled={save.isPending}>
        <label className="checkbox task-structure-check">
          <input
            type="checkbox"
            checked={priority === "high"}
            onChange={(event) => {
              setPriority(event.target.checked ? "high" : "none");
              changed();
            }}
          />
          Hohe Priorität
        </label>
        <fieldset className="task-fields task-structure-tags">
          <legend className="field-label">Schlagworte</legend>
          {tags.isPending ? (
            <p className="field-hint" role="status">
              Schlagworte werden geladen …
            </p>
          ) : tags.isError ? (
            <p className="field-hint" role="status">
              Schlagworte konnten nicht geladen werden.
            </p>
          ) : tags.data.items.length === 0 ? (
            <p className="field-hint">
              Diese Liste hat noch keine Schlagworte.
            </p>
          ) : (
            tags.data.items.map((tag) => (
              <label className="checkbox task-structure-check" key={tag.id}>
                <input
                  type="checkbox"
                  checked={tagIds.includes(tag.id)}
                  onChange={(event) => {
                    setTagIds((current) =>
                      event.target.checked
                        ? [...current, tag.id]
                        : current.filter((value) => value !== tag.id),
                    );
                    changed();
                  }}
                />
                {tag.title}
              </label>
            ))
          )}
          <div className="task-structure-add">
            <label className="field">
              <span className="field-label">Neues Schlagwort</span>
              <input
                className="input"
                maxLength={40}
                value={newTag}
                onChange={(event) => {
                  setNewTag(event.target.value);
                  tagOperation.current = crypto.randomUUID();
                  createTag.reset();
                }}
              />
            </label>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={!newTag.trim() || createTag.isPending}
              onClick={() => createTag.mutate()}
            >
              Schlagwort anlegen
            </Button>
          </div>
          {createTag.error && (
            <p className="field-error" role="status">
              {createTag.error instanceof ApiError &&
              createTag.error.status === 409
                ? "Dieses Schlagwort gibt es in der Liste schon."
                : "Das Schlagwort konnte nicht angelegt werden."}
            </p>
          )}
        </fieldset>
        {save.error && (
          <StatusMessage tone="error">
            <p>
              {save.error instanceof ApiError && save.error.status === 409
                ? says(
                    address,
                    "Die Aufgabe wurde inzwischen geändert oder ein Schlagwort ist nicht mehr verfügbar. Deine Auswahl bleibt erhalten; lade die Aufgabe neu und speichere erneut.",
                    "Die Aufgabe wurde inzwischen geändert oder ein Schlagwort ist nicht mehr verfügbar. Ihre Auswahl bleibt erhalten; laden Sie die Aufgabe neu und speichern Sie erneut.",
                  )
                : "Priorität und Schlagworte konnten nicht gespeichert werden."}
            </p>
          </StatusMessage>
        )}
        {save.isSuccess && (
          <p className="field-hint" role="status">
            Gespeichert.
          </p>
        )}
        <div className="task-form-actions">
          <Button type="submit" variant="secondary" loading={save.isPending}>
            {save.isPending ? "Wird gespeichert …" : "Speichern"}
          </Button>
        </div>
      </fieldset>
    </form>
  );
}

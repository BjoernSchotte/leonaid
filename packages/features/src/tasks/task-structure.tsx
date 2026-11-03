import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, IconButton, StatusMessage } from "@leonaid/ui";
import { Trash2 } from "lucide-react";

import { says, type Address } from "./task-copy";
import type { Task } from "./task-editor";

type ChecklistStep = Task["checklist"][number];

/**
 * Priority, list tags and checklist of one task. They are saved together in
 * one task revision, separate from the main editor, so a conflict keeps the
 * draft of both forms. Without a draft the form follows newer revisions of
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
  const [checklist, setChecklist] = useState<ChecklistStep[]>(task.checklist);
  const [newStep, setNewStep] = useState("");
  const [newTag, setNewTag] = useState("");
  const dirty =
    priority !== base.priority ||
    tagIds.join(" ") !== base.tags.map((tag) => tag.id).join(" ") ||
    JSON.stringify(checklist) !== JSON.stringify(base.checklist) ||
    newStep.trim() !== "";
  useEffect(() => {
    if (dirty || task.revision === base.revision) return;
    setBase(task);
    setPriority(task.priority);
    setTagIds(task.tags.map((tag) => tag.id));
    setChecklist(task.checklist);
  }, [base.revision, dirty, task]);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
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
        expectedRevision: base.revision,
        priority,
        tagIds,
        checklist,
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
        Priorität, Tags und Checkliste
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
          <legend className="field-label">Tags</legend>
          {tags.isPending ? (
            <p className="field-hint" role="status">
              Tags werden geladen …
            </p>
          ) : tags.isError ? (
            <p className="field-hint" role="status">
              Tags konnten nicht geladen werden.
            </p>
          ) : tags.data.items.length === 0 ? (
            <p className="field-hint">Diese Liste hat noch keine Tags.</p>
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
              <span className="field-label">Neuer Tag</span>
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
              Tag anlegen
            </Button>
          </div>
          {createTag.error && (
            <p className="field-error" role="status">
              {createTag.error instanceof ApiError &&
              createTag.error.status === 409
                ? "Diesen Tag gibt es in der Liste schon."
                : "Der Tag konnte nicht angelegt werden."}
            </p>
          )}
        </fieldset>
        <fieldset className="task-fields task-structure-checklist">
          <legend className="field-label">Checkliste</legend>
          {checklist.length === 0 && (
            <p className="field-hint">Noch keine Schritte.</p>
          )}
          <ul>
            {checklist.map((step, index) => (
              <li key={step.id}>
                <input
                  type="checkbox"
                  aria-label={`Schritt ${index + 1} erledigt`}
                  checked={step.done}
                  onChange={(event) => {
                    setChecklist((current) =>
                      current.map((item) =>
                        item.id === step.id
                          ? { ...item, done: event.target.checked }
                          : item,
                      ),
                    );
                    changed();
                  }}
                />
                <input
                  className="input"
                  aria-label={`Schritt ${index + 1}`}
                  maxLength={500}
                  required
                  value={step.text}
                  onChange={(event) => {
                    setChecklist((current) =>
                      current.map((item) =>
                        item.id === step.id
                          ? { ...item, text: event.target.value }
                          : item,
                      ),
                    );
                    changed();
                  }}
                />
                <IconButton
                  icon={Trash2}
                  label={`Schritt ${index + 1} entfernen`}
                  size="sm"
                  onClick={() => {
                    setChecklist((current) =>
                      current.filter((item) => item.id !== step.id),
                    );
                    changed();
                  }}
                />
              </li>
            ))}
          </ul>
          <div className="task-structure-add">
            <label className="field">
              <span className="field-label">Neuer Schritt</span>
              <input
                className="input"
                maxLength={500}
                value={newStep}
                onChange={(event) => setNewStep(event.target.value)}
              />
            </label>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={!newStep.trim() || checklist.length >= 100}
              onClick={() => {
                setChecklist((current) => [
                  ...current,
                  {
                    id: crypto.randomUUID(),
                    text: newStep.trim(),
                    done: false,
                  },
                ]);
                setNewStep("");
                changed();
              }}
            >
              Schritt hinzufügen
            </Button>
          </div>
        </fieldset>
        {save.error && (
          <StatusMessage tone="error">
            <p>
              {save.error instanceof ApiError && save.error.status === 409
                ? says(
                    address,
                    "Die Aufgabe wurde inzwischen geändert oder ein Tag ist nicht mehr verfügbar. Deine Auswahl bleibt erhalten; lade die Aufgabe neu und speichere erneut.",
                    "Die Aufgabe wurde inzwischen geändert oder ein Tag ist nicht mehr verfügbar. Ihre Auswahl bleibt erhalten; laden Sie die Aufgabe neu und speichern Sie erneut.",
                  )
                : "Priorität, Tags und Checkliste konnten nicht gespeichert werden."}
            </p>
          </StatusMessage>
        )}
        {save.isSuccess && (
          <p className="field-hint" role="status">
            Struktur gespeichert.
          </p>
        )}
        <div className="task-form-actions">
          <Button
            type="submit"
            variant="secondary"
            disabled={checklist.some((step) => !step.text.trim())}
            loading={save.isPending}
          >
            {save.isPending ? "Wird gespeichert …" : "Struktur speichern"}
          </Button>
        </div>
      </fieldset>
    </form>
  );
}

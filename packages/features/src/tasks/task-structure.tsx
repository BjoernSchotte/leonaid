import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";

import type { Task } from "./task-editor";

type ChecklistStep = Task["checklist"][number];

/** Compact, read-only summary of priority, tags and checklist progress. */
export function TaskStructureSummary({ task }: { task: Task }) {
  const done = task.checklist.filter((step) => step.done).length;
  return (
    <>
      {task.priority === "high" && (
        <span className="task-priority">Hohe Priorität</span>
      )}
      {task.tags.map((tag) => (
        <span className="task-tag" key={tag.id}>
          #{tag.title}
        </span>
      ))}
      {task.checklist.length > 0 && (
        <span>
          Checkliste {done}/{task.checklist.length}
        </span>
      )}
    </>
  );
}

/**
 * Priority, list tags and checklist of one task. They are saved together in
 * one task revision, separate from the main editor, so a conflict keeps the
 * draft of both forms.
 */
export function TaskStructurePanel({
  client,
  task,
}: {
  client: LeonAidApiClient;
  task: Task;
}) {
  const id = useId();
  const cache = useQueryClient();
  const operation = useRef(crypto.randomUUID());
  const tagOperation = useRef(crypto.randomUUID());
  const [priority, setPriority] = useState(task.priority);
  const [tagIds, setTagIds] = useState(task.tags.map((tag) => tag.id));
  const [checklist, setChecklist] = useState<ChecklistStep[]>(task.checklist);
  const [newStep, setNewStep] = useState("");
  const [newTag, setNewTag] = useState("");
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
        expectedRevision: task.revision,
        priority,
        tagIds,
        checklist,
      }),
    onSuccess: async () => {
      operation.current = crypto.randomUUID();
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
      className="task-structure"
      aria-labelledby={`${id}-heading`}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h2 id={`${id}-heading`}>Priorität, Tags und Checkliste</h2>
      <fieldset disabled={save.isPending}>
        <label className="task-structure-check">
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
        <fieldset className="task-structure-tags">
          <legend>Tags</legend>
          {tags.isPending ? (
            <p role="status">Tags werden geladen …</p>
          ) : tags.isError ? (
            <p role="status">Tags konnten nicht geladen werden.</p>
          ) : tags.data.items.length === 0 ? (
            <p>Diese Liste hat noch keine Tags.</p>
          ) : (
            tags.data.items.map((tag) => (
              <label className="task-structure-check" key={tag.id}>
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
            <label>
              Neuer Tag
              <input
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
              variant="secondary"
              disabled={!newTag.trim() || createTag.isPending}
              onClick={() => createTag.mutate()}
            >
              Tag anlegen
            </Button>
          </div>
          {createTag.error && (
            <p role="status">
              {createTag.error instanceof ApiError &&
              createTag.error.status === 409
                ? "Diesen Tag gibt es in der Liste schon."
                : "Der Tag konnte nicht angelegt werden."}
            </p>
          )}
        </fieldset>
        <fieldset className="task-structure-checklist">
          <legend>Checkliste</legend>
          {checklist.length === 0 && <p>Noch keine Schritte.</p>}
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
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setChecklist((current) =>
                      current.filter((item) => item.id !== step.id),
                    );
                    changed();
                  }}
                >
                  Schritt entfernen
                </Button>
              </li>
            ))}
          </ul>
          <div className="task-structure-add">
            <label>
              Neuer Schritt
              <input
                maxLength={500}
                value={newStep}
                onChange={(event) => setNewStep(event.target.value)}
              />
            </label>
            <Button
              type="button"
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
                ? "Die Aufgabe wurde inzwischen geändert oder ein Tag ist nicht mehr verfügbar. Deine Auswahl bleibt erhalten; lade die Aufgabe neu und speichere erneut."
                : "Priorität, Tags und Checkliste konnten nicht gespeichert werden."}
            </p>
          </StatusMessage>
        )}
        {save.isSuccess && <p role="status">Struktur gespeichert.</p>}
        <Button
          type="submit"
          disabled={checklist.some((step) => !step.text.trim())}
        >
          {save.isPending ? "Wird gespeichert …" : "Struktur speichern"}
        </Button>
      </fieldset>
    </form>
  );
}

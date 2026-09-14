import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Node, posToDOMRect } from "@tiptap/core";
import {
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  type NodeViewProps,
} from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import { NodeSelection } from "@tiptap/pm/state";
import StarterKit from "@tiptap/starter-kit";
import { TextStyle, FontFamily, FontSize } from "@tiptap/extension-text-style";
import TextAlign from "@tiptap/extension-text-align";
import { FormattingToolbar } from "./formatting-toolbar";
import { normalizePastedHTML } from "./paste";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import "./knowledge.css";
import { materialReference } from "./material-reference";
import { MaterialPicker } from "../materials/picker";
import { TaskFromPage } from "./task-from-page";
import { AccessMembersPanel } from "../shared/access-members";

type Page = Awaited<ReturnType<LeonAidApiClient["getKnowledgePage"]>>;

function taskReference(client: LeonAidApiClient, basePath: string) {
  function Reference({ node }: NodeViewProps) {
    const id = String(node.attrs.taskId);
    const task = useQuery({
      queryKey: ["task", id],
      queryFn: () => client.getTask(id),
      retry: false,
      refetchInterval: 30000,
    });
    return (
      <NodeViewWrapper
        className="knowledge-task-reference"
        contentEditable={false}
      >
        {task.error ? (
          "Aufgabe nicht verfügbar"
        ) : task.data ? (
          <a
            href={`${basePath.replace(/knowledge$/, "tasks")}/${task.data.listId}`}
          >
            {task.data.title} ·{" "}
            {task.data.status === "done" ? "Erledigt" : "Offen"}
          </a>
        ) : (
          "Aufgabe wird geladen …"
        )}
      </NodeViewWrapper>
    );
  }
  return Node.create({
    name: "taskReference",
    group: "block",
    atom: true,
    addAttributes: () => ({ taskId: { default: null } }),
    parseHTML: () => [
      {
        tag: "div[data-task-reference]",
        getAttrs: (element) => ({
          taskId: element.getAttribute("data-task-reference"),
        }),
      },
    ],
    renderHTML: ({ node }) => [
      "div",
      { "data-task-reference": node.attrs.taskId },
      "Aufgabe",
    ],
    addNodeView: () => ReactNodeViewRenderer(Reference),
  });
}

export function KnowledgeEditorPage({
  client,
  identity,
  pageId,
  basePath,
}: ModulePageContext & { pageId: string; basePath: string }) {
  const [generation, setGeneration] = useState(0);
  const page = useQuery({
    queryKey: ["knowledge-page", pageId],
    queryFn: () => client.getKnowledgePage(pageId),
    retry: false,
  });
  const rights = useQuery({
    queryKey: ["knowledge-permissions", pageId],
    queryFn: () => client.getKnowledgePagePermissions(pageId),
    retry: false,
    refetchInterval: 30000,
  });
  const reload = async () => {
    if (
      !window.confirm(
        "Aktuelle Version laden und deinen ungespeicherten Entwurf verwerfen?",
      )
    )
      return;
    const response = await page.refetch();
    if (response.isSuccess) setGeneration((value) => value + 1);
    await rights.refetch();
  };
  return (
    <section className="knowledge-workspace" aria-labelledby="page-heading">
      <a href={basePath}>Zur Seitenübersicht</a>
      {(page.error || rights.error) && (
        <StatusMessage tone="error">
          <p>Die Seite ist nicht verfügbar oder dein Zugriff wurde geändert.</p>
          <Button
            variant="secondary"
            onClick={() => {
              void page.refetch();
              void rights.refetch();
            }}
          >
            Erneut laden
          </Button>
        </StatusMessage>
      )}
      {page.data && rights.data ? (
        <PageEditor
          key={`${pageId}:${generation}`}
          client={client}
          page={page.data}
          userId={identity.userId}
          canEdit={rights.data.canEdit && !page.error && !rights.error}
          canManage={rights.data.canManage && !page.error && !rights.error}
          basePath={basePath}
          reload={reload}
        />
      ) : !page.error && !rights.error ? (
        <p role="status">Seite wird geladen …</p>
      ) : (
        <h1 id="page-heading">Seite nicht verfügbar</h1>
      )}
    </section>
  );
}

function PageEditor({
  client,
  userId,
  page,
  canEdit,
  canManage,
  basePath,
  reload,
}: {
  client: LeonAidApiClient;
  page: Page;
  userId: string;
  canEdit: boolean;
  canManage: boolean;
  basePath: string;
  reload: () => Promise<void>;
}) {
  const [title, setTitle] = useState(page.title);
  const [savedTitle, setSavedTitle] = useState(page.title);
  const [revision, setRevision] = useState(page.revision);
  const [taskOpen, setTaskOpen] = useState(false);
  const [materialOpen, setMaterialOpen] = useState(false);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const materialTrigger = useRef<HTMLButtonElement>(null);
  const taskTrigger = useRef<HTMLButtonElement>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const operation = useRef(crypto.randomUUID());
  const extensions = useMemo(
    () => [
      StarterKit.configure({
        trailingNode: false,
        link: {
          openOnClick: false,
          autolink: false,
          linkOnPaste: false,
          isAllowedUri: (url) => /^https?:\/\//i.test(url),
        },
      }),
      TextStyle,
      FontFamily,
      FontSize,
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      taskReference(client, basePath),
      materialReference(client),
    ],
    [client, basePath],
  );
  const changed = () => {
    setDirty(true);
    setSaved(false);
    operation.current = crypto.randomUUID();
  };
  const editor = useEditor({
    extensions,
    content: page.content,
    editable: canEdit,
    enableContentCheck: true,
    onContentError: () => setInvalid(true),
    onUpdate: changed,
    editorProps: {
      transformPastedHTML: normalizePastedHTML,
      attributes: {
        role: "textbox",
        "aria-label": "Seiteninhalt",
        "aria-multiline": "true",
        class: "knowledge-document",
      },
    },
  });
  const save = useMutation({
    mutationFn: () =>
      client.updateKnowledgePage(page.id, {
        title: title.trim(),
        content: editor!.getJSON(),
        expectedRevision: revision,
        idempotencyKey: operation.current,
      }),
    onSuccess: (next) => {
      setRevision(next.revision);
      setSavedTitle(next.title);
      setDirty(false);
      setSaved(true);
      operation.current = crypto.randomUUID();
    },
  });
  useEffect(() => {
    editor?.setEditable(
      canEdit && !save.isPending && !invalid && !taskOpen,
      false,
    );
  }, [editor, canEdit, save.isPending, invalid, taskOpen]);
  useEffect(() => {
    if (!dirty && !taskOpen) return;
    const prevent = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty, taskOpen]);
  return (
    <div className="knowledge-page-editor">
      <header className="knowledge-editor-header">
        <h1
          id="page-heading"
          className={canEdit ? "knowledge-visually-hidden" : undefined}
        >
          {savedTitle}
        </h1>
        {canEdit && (
          <label>
            Seitentitel
            <input
              maxLength={240}
              required
              value={title}
              disabled={save.isPending || taskOpen}
              onChange={(event) => {
                setTitle(event.target.value);
                changed();
              }}
            />
          </label>
        )}
        <div className="knowledge-editor-meta">
          <span>
            Version {revision}
            {!canEdit
              ? " · Nur lesen"
              : dirty
                ? " · Ungespeicherte Änderungen"
                : ""}
          </span>
          {canEdit && (
            <div className="knowledge-toolbar">
              <Button
                disabled={
                  !editor ||
                  !dirty ||
                  !title.trim() ||
                  save.isPending ||
                  invalid ||
                  taskOpen
                }
                onClick={() => save.mutate()}
              >
                {save.isPending ? "Wird gespeichert …" : "Speichern"}
              </Button>
              <Button
                variant="secondary"
                disabled={save.isPending || taskOpen}
                onClick={() => void reload()}
              >
                Aktuelle Version laden
              </Button>
            </div>
          )}
        </div>
      </header>
      <div className="knowledge-editor-actions">
        {canManage && (
          <details className="knowledge-access">
            <summary>Freigaben verwalten</summary>
            <AccessMembersPanel
              client={client}
              objectId={page.id}
              kind="knowledge-page"
              actionScoped={!!page.actionId}
            />
          </details>
        )}
        {canEdit && (
          <details className="knowledge-insert">
            <summary>Einfügen</summary>
            <div className="knowledge-insert-options">
              <Button
                variant="secondary"
                disabled={
                  !editor ||
                  materialOpen ||
                  taskOpen ||
                  invalid ||
                  save.isPending
                }
                onClick={(event) => {
                  materialTrigger.current = event.currentTarget;
                  setMaterialOpen(true);
                }}
              >
                Material aus Ablage verknüpfen
              </Button>
              {canEdit && (
                <>
                  <Button
                    variant="secondary"
                    disabled={
                      !editor || dirty || save.isPending || invalid || taskOpen
                    }
                    onClick={(event) => {
                      taskTrigger.current = event.currentTarget;
                      setTaskOpen(true);
                    }}
                  >
                    Aufgabe aus dieser Seite
                  </Button>
                  {dirty && (
                    <p>
                      Speichere deine Seitenänderungen, bevor du eine Aufgabe
                      daraus anlegst.
                    </p>
                  )}
                </>
              )}
            </div>
          </details>
        )}
      </div>
      {invalid && (
        <StatusMessage tone="error">
          <p>
            Dieser Inhalt kann nicht vollständig dargestellt werden. Speichern
            ist gesperrt, damit nichts verloren geht.
          </p>
        </StatusMessage>
      )}
      {canEdit && editor && (
        <FormattingToolbar
          editor={editor}
          disabled={save.isPending || invalid || taskOpen}
        />
      )}
      {canEdit && !taskOpen && !invalid && !save.isPending && (
        <>
          {materialOpen && (
            <MaterialPicker
              client={client}
              onClose={() => {
                setMaterialOpen(false);
                requestAnimationFrame(() => materialTrigger.current?.focus());
              }}
              onInsert={(materialId, version) => {
                if (
                  editor
                    ?.chain()
                    .focus()
                    .insertContent({
                      type: "materialReference",
                      attrs: { materialId, version },
                    })
                    .run()
                )
                  setMaterialOpen(false);
              }}
            />
          )}
        </>
      )}
      {canEdit && editor && (
        <BubbleMenu
          editor={editor}
          ref={bubbleRef}
          pluginKey="knowledgeSelection"
          className="knowledge-selection-menu"
          getReferencedVirtualElement={() => {
            const { selection, doc } = editor.state;
            // Select All includes the document boundary; anchor inside the text
            // blocks instead of the tall, otherwise empty writing surface.
            const rect = posToDOMRect(
              editor.view,
              Math.max(1, selection.from),
              Math.min(doc.content.size - 1, selection.to),
            );
            return { getBoundingClientRect: () => rect };
          }}
          options={{
            strategy: "fixed",
            placement: "top",
            offset: 8,
            flip: { padding: 12 },
            shift: { padding: { top: 12, bottom: 100, left: 12, right: 12 } },
          }}
          shouldShow={({ editor: current, state }) =>
            current.isEditable &&
            !(state.selection instanceof NodeSelection) &&
            !!state.doc.textBetween(state.selection.from, state.selection.to)
              .length &&
            !state.selection.empty &&
            (current.isFocused ||
              !!bubbleRef.current?.contains(document.activeElement))
          }
          onKeyDown={(event) => {
            if (event.nativeEvent.key === "Escape") {
              event.preventDefault();
              editor
                .chain()
                .focus()
                .setTextSelection(editor.state.selection.to)
                .run();
              editor.view.dispatch(
                editor.state.tr.setMeta("knowledgeSelection", "hide"),
              );
            }
          }}
        >
          <FormattingToolbar
            editor={editor}
            compact
            disabled={save.isPending || invalid || taskOpen}
          />
        </BubbleMenu>
      )}
      <EditorContent editor={editor} />
      {save.error && (
        <StatusMessage tone="error">
          <p>
            {save.error instanceof ApiError && save.error.status === 409
              ? "Die Seite wurde inzwischen geändert. Dein Entwurf bleibt erhalten. Lade die aktuelle Version erst, nachdem du deine Änderungen gesichert hast."
              : "Speichern fehlgeschlagen. Dein Entwurf bleibt erhalten; prüfe deine Verbindung oder Zugriffsrechte und versuche es erneut."}
          </p>
        </StatusMessage>
      )}
      {saved && <p role="status">Gespeichert.</p>}
      {taskOpen && (
        <TaskFromPage
          client={client}
          userId={userId}
          onClose={() => {
            setTaskOpen(false);
            requestAnimationFrame(() => taskTrigger.current?.focus());
          }}
          createTask={async (listId, command) => {
            const result = await client.createTaskFromKnowledgePage(page.id, {
              ...command,
              listId,
              expectedRevision: revision,
            });
            editor!.commands.setContent(result.page.content, {
              emitUpdate: false,
            });
            setRevision(result.page.revision);
            setSavedTitle(result.page.title);
            setTitle(result.page.title);
            setDirty(false);
            setSaved(true);
            return result.task;
          }}
        />
      )}
    </div>
  );
}

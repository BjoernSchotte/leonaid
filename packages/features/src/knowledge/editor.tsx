import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  GitMerge,
  History,
  ListChecks,
  PenLine,
  Save,
  Users,
} from "lucide-react";
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

import {
  ClassFontFamily,
  ClassFontSize,
  ClassTextAlign,
  ClassTextStyle,
  ReplaceSelectionInput,
} from "./class-formatting";
import { FormattingToolbar } from "./formatting-toolbar";
import { normalizePastedHTML } from "./paste";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import {
  Button,
  Modal,
  NextStep,
  ReadOnlyNotice,
  StatusMessage,
  useDiscardDialog,
  useHotkeys,
  useLeaveGuard,
  useOptionalToast,
} from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import { knowledgeAddress } from "./knowledge";
import "./knowledge.css";
import { materialReference } from "./material-reference";
import { MaterialPicker } from "../materials/picker";
import { TaskFromPage } from "./task-from-page";
import {
  AccessMembersPanel,
  type AccessMemberSource,
} from "../shared/access-members";

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
            href={`${basePath.replace(/knowledge$/, "tasks")}/${task.data.listId}?view=all&open=${task.data.id}`}
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

function pageMemberSource(
  client: LeonAidApiClient,
  pageId: string,
): AccessMemberSource {
  return {
    queryKey: "knowledge-members",
    label: "Seitenfreigaben",
    accessLabel: "Seitenzugriff",
    subject: "diese Seite",
    list: async (search, offset) => {
      const result = await client.listKnowledgePageMembers(pageId, {
        search,
        offset,
      });
      return { ...result, revision: result.accessRevision };
    },
    change: (command, expectedRevision, idempotencyKey) => {
      const common = {
        expectedAccessRevision: expectedRevision,
        idempotencyKey,
      };
      return "email" in command
        ? client.setKnowledgePageMemberByEmail(pageId, {
            ...common,
            ...command,
          })
        : client.setKnowledgePageMember(pageId, { ...common, ...command });
    },
    dependentQueryKeys: [
      ["knowledge-permissions", pageId],
      ["knowledge-page", pageId],
    ],
  };
}

type Address = "Sie" | "du";
const says = (address: Address, du: string, sie: string) =>
  address === "du" ? du : sie;

export function KnowledgeEditorPage({
  client,
  identity,
  pageId,
  basePath,
  surface,
}: ModulePageContext & {
  pageId: string;
  basePath: string;
  surface?: "web" | "pwa";
}) {
  const address = knowledgeAddress(basePath, surface);
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
  const action = page.data?.actionId
    ? (identity.actionMemberships.find(
        (membership) => membership.actionId === page.data!.actionId,
      )?.actionName ?? "Charity-Aktion")
    : null;
  return (
    <div className="knowledge-page" data-zone="knowledge">
      {(page.error || rights.error) && (
        <>
          <nav aria-label="Brotkrumen" className="crumbs">
            <a href={basePath}>Wissen</a>
          </nav>
          <h1 id="page-heading">Seite nicht verfügbar</h1>
          <StatusMessage tone="error">
            <p>
              {says(
                address,
                "Die Seite ist nicht verfügbar oder dein Zugriff wurde geändert.",
                "Die Seite ist nicht verfügbar oder Ihr Zugriff wurde geändert.",
              )}
            </p>
            <Button
              onClick={() => {
                void page.refetch();
                void rights.refetch();
              }}
              size="sm"
              variant="secondary"
            >
              Erneut laden
            </Button>
          </StatusMessage>
        </>
      )}
      {page.data && rights.data && !page.error && !rights.error ? (
        <PageEditor
          action={action}
          address={address}
          basePath={basePath}
          canEdit={rights.data.canEdit}
          canManage={rights.data.canManage}
          client={client}
          key={pageId}
          page={page.data}
          userId={identity.userId}
        />
      ) : !page.error && !rights.error ? (
        <p className="small subtle" role="status">
          Seite wird geladen …
        </p>
      ) : null}
    </div>
  );
}

type Conflict = {
  readonly revision: number;
  readonly title: string;
  readonly content: Page["content"];
};

function isEmptyContent(content: Page["content"]): boolean {
  const nodes = (content as { content?: { content?: unknown[] }[] }).content;
  return !nodes?.length || nodes.every((node) => !node.content?.length);
}

/** Consumes `?edit` (a new page opens for writing). */
function takeEditRequest(): boolean {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("edit")) return false;
  url.searchParams.delete("edit");
  window.history.replaceState(window.history.state, "", url);
  return true;
}

function PageEditor({
  action,
  address,
  basePath,
  canEdit,
  canManage,
  client,
  page,
  userId,
}: {
  action: string | null;
  address: Address;
  basePath: string;
  canEdit: boolean;
  canManage: boolean;
  client: LeonAidApiClient;
  page: Page;
  userId: string;
}) {
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const { confirmDiscard, dialog: discardDialog } = useDiscardDialog(address);
  const [editing, setEditing] = useState(() => takeEditRequest() && canEdit);
  const [title, setTitle] = useState(page.title);
  const [savedTitle, setSavedTitle] = useState(page.title);
  const [revision, setRevision] = useState(page.revision);
  const savedContent = useRef(page.content);
  const [taskOpen, setTaskOpen] = useState(false);
  const [materialOpen, setMaterialOpen] = useState(false);
  const [accessOpen, setAccessOpen] = useState(false);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [empty, setEmpty] = useState(() => isEmptyContent(page.content));
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
      ClassTextStyle,
      ClassFontFamily,
      ClassFontSize,
      ClassTextAlign,
      ReplaceSelectionInput,
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
    // Tiptap would inject a <style> element, which strict CSP blocks; the
    // editor styles ship in knowledge.css instead.
    injectCSS: false,
    content: page.content,
    editable: canEdit && editing,
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
    mutationFn: (expectedRevision: number) =>
      client.updateKnowledgePage(page.id, {
        title: title.trim(),
        content: editor!.getJSON(),
        expectedRevision,
        idempotencyKey: operation.current,
      }),
    onSuccess: (next) => {
      setRevision(next.revision);
      setSavedTitle(next.title);
      savedContent.current = next.content;
      setEmpty(isEmptyContent(next.content));
      setDirty(false);
      setSaved(true);
      setConflict(null);
      setEditing(false);
      operation.current = crypto.randomUUID();
      cache.setQueryData(["knowledge-page", page.id], next);
      void cache.invalidateQueries({ queryKey: ["knowledge-pages"] });
    },
    onError: async (error) => {
      if (!(error instanceof ApiError) || error.status !== 409) return;
      // Someone saved in between: show their revision and let the person
      // choose; the draft stays in the editor.
      try {
        const latest = await client.getKnowledgePage(page.id);
        setConflict({
          revision: latest.revision,
          title: latest.title,
          content: latest.content,
        });
      } catch {
        // The plain error below still explains what happened.
      }
    },
  });
  // A newer revision from a refetch replaces the shown page while nobody
  // is writing.
  useEffect(() => {
    if (!editor || editing || dirty || page.revision <= revision) return;
    editor.commands.setContent(page.content, { emitUpdate: false });
    savedContent.current = page.content;
    setRevision(page.revision);
    setSavedTitle(page.title);
    setTitle(page.title);
    setEmpty(isEmptyContent(page.content));
  }, [dirty, editing, editor, page, revision]);
  // Into the text when writing starts, in the same task that makes the
  // document editable (nothing can put a cursor in between).
  const focusOnEdit = useRef(editing);
  useEffect(() => {
    const writable =
      canEdit && editing && !save.isPending && !invalid && !taskOpen;
    editor?.setEditable(writable, false);
    if (writable && focusOnEdit.current) {
      focusOnEdit.current = false;
      // Synchronously: Tiptap's focus command waits a frame, long enough
      // for a click into the text to be moved to the end afterwards.
      if (editor) {
        editor.commands.setTextSelection(editor.state.doc.content.size);
        editor.view.focus();
      }
    }
  }, [editor, canEdit, editing, save.isPending, invalid, taskOpen]);
  useLeaveGuard(dirty || taskOpen);

  const startEditing = () => {
    if (!canEdit) return;
    setEditing(true);
    setSaved(false);
    focusOnEdit.current = true;
  };
  const resetDraft = () => {
    editor?.commands.setContent(savedContent.current, { emitUpdate: false });
    setTitle(savedTitle);
    setDirty(false);
    setConflict(null);
    save.reset();
    setEditing(false);
  };
  const cancelEditing = async () => {
    if (dirty && !(await confirmDiscard())) return;
    resetDraft();
  };
  const takeOther = () => {
    if (!conflict) return;
    editor?.commands.setContent(conflict.content, { emitUpdate: false });
    savedContent.current = conflict.content;
    setRevision(conflict.revision);
    setSavedTitle(conflict.title);
    setTitle(conflict.title);
    setEmpty(isEmptyContent(conflict.content));
    setDirty(false);
    setConflict(null);
    save.reset();
    setEditing(false);
    toast?.show({
      title: `Fassung ${conflict.revision} übernommen.`,
      tone: "success",
    });
  };
  const canSave =
    !!editor &&
    dirty &&
    !!title.trim() &&
    !save.isPending &&
    !invalid &&
    !taskOpen;
  useHotkeys([
    {
      keys: "e",
      label: "Seite bearbeiten",
      group: "Wissen",
      when: () => canEdit && !editing,
      run: startEditing,
    },
    {
      keys: "mod+s",
      label: "Speichern",
      group: "Wissen",
      allowInInput: true,
      when: () => editing,
      run: (event) => {
        event?.preventDefault();
        if (canSave) save.mutate(revision);
      },
    },
    {
      keys: "escape",
      label: "Bearbeiten beenden / zur Übersicht",
      group: "Wissen",
      when: () => !materialOpen && !taskOpen,
      run: () => {
        if (editing) void cancelEditing();
        else window.location.assign(basePath);
      },
    },
  ]);

  return (
    <div
      className={
        editing ? "knowledge-page-editor is-editing" : "knowledge-page-editor"
      }
    >
      <nav aria-label="Brotkrumen" className="crumbs">
        <a href={basePath}>Wissen</a>
        <span aria-hidden="true">/</span>
        <span>{savedTitle}</span>
      </nav>
      <header className="page-header">
        <div>
          <div className="page-heading">
            <h1 id="page-heading">{savedTitle}</h1>
          </div>
          <p className="page-sub">
            {action ?? "Eigenständig"} · Fassung {revision}
            {!canEdit
              ? " · Nur lesen"
              : dirty
                ? " · Ungespeicherte Änderungen"
                : ""}
          </p>
        </div>
        <div className="page-actions">
          {editing ? (
            <>
              <Button
                disabled={save.isPending}
                onClick={() => void cancelEditing()}
                variant="ghost"
              >
                Abbrechen
              </Button>
              <Button
                disabled={!canSave}
                icon={Save}
                loading={save.isPending}
                onClick={() => save.mutate(revision)}
                shortcut="mod+s"
                variant="primary"
              >
                {save.isPending ? "Wird gespeichert …" : "Speichern"}
              </Button>
            </>
          ) : (
            <>
              {canManage ? (
                <Button
                  icon={Users}
                  onClick={() => setAccessOpen(true)}
                  variant="ghost"
                >
                  Freigaben verwalten
                </Button>
              ) : null}
              {canEdit ? (
                <>
                  <Button
                    disabled={!editor || dirty || invalid || taskOpen}
                    icon={ListChecks}
                    onClick={(event) => {
                      taskTrigger.current = event.currentTarget;
                      setTaskOpen(true);
                    }}
                    variant="ghost"
                  >
                    Aufgabe aus dieser Seite
                  </Button>
                  <Button
                    icon={PenLine}
                    onClick={startEditing}
                    shortcut="e"
                    variant="secondary"
                  >
                    Bearbeiten
                  </Button>
                </>
              ) : null}
            </>
          )}
        </div>
      </header>

      {!canEdit ? (
        <ReadOnlyNotice>
          {says(
            address,
            "Du kannst diese Seite lesen; bearbeiten dürfen die Personen mit Bearbeitungsrecht.",
            "Sie können diese Seite lesen; bearbeiten dürfen die Personen mit Bearbeitungsrecht.",
          )}
        </ReadOnlyNotice>
      ) : empty && !editing ? (
        <NextStep
          action={
            <Button icon={PenLine} onClick={startEditing} variant="primary">
              Bearbeiten
            </Button>
          }
          consequence={says(
            address,
            "Die Seite ist noch leer. Schreib den ersten Abschnitt – gespeichert wird erst mit „Speichern“.",
            "Die Seite ist noch leer. Schreiben Sie den ersten Abschnitt – gespeichert wird erst mit „Speichern“.",
          )}
        />
      ) : null}

      {conflict ? (
        <div className="callout tone-warn conflict" role="alert">
          <GitMerge aria-hidden="true" size={16} />
          <div className="stack">
            <p>
              <strong>
                Die Seite wurde inzwischen geändert (Fassung {conflict.revision}
                ).
              </strong>{" "}
              {says(
                address,
                "Deine Änderungen sind noch nicht gespeichert. Wie möchtest du weitermachen?",
                "Ihre Änderungen sind noch nicht gespeichert. Wie möchten Sie weitermachen?",
              )}
            </p>
            <div className="cluster">
              <Button
                disabled={save.isPending}
                onClick={() => save.mutate(conflict.revision)}
                size="sm"
                variant="primary"
              >
                Meine Fassung behalten
              </Button>
              <Button disabled={save.isPending} onClick={takeOther} size="sm">
                Andere übernehmen
              </Button>
            </div>
          </div>
        </div>
      ) : save.error ? (
        <StatusMessage tone="error">
          <p>
            {save.error instanceof ApiError && save.error.status === 409
              ? says(
                  address,
                  "Die Seite wurde inzwischen geändert. Dein Entwurf bleibt erhalten.",
                  "Die Seite wurde inzwischen geändert. Ihr Entwurf bleibt erhalten.",
                )
              : says(
                  address,
                  "Speichern fehlgeschlagen. Dein Entwurf bleibt erhalten; prüfe deine Verbindung oder Zugriffsrechte und versuche es erneut.",
                  "Speichern fehlgeschlagen. Ihr Entwurf bleibt erhalten; prüfen Sie Ihre Verbindung oder Zugriffsrechte und versuchen Sie es erneut.",
                )}
          </p>
        </StatusMessage>
      ) : null}
      {invalid && (
        <StatusMessage tone="error">
          <p>
            Dieser Inhalt kann nicht vollständig dargestellt werden. Speichern
            ist gesperrt, damit nichts verloren geht.
          </p>
        </StatusMessage>
      )}

      {editing ? (
        <div className="format-bar">
          <label className="field knowledge-title-field">
            <span className="field-label">Seitentitel</span>
            <input
              className="input"
              disabled={save.isPending || taskOpen}
              maxLength={240}
              onChange={(event) => {
                setTitle(event.target.value);
                changed();
              }}
              required
              value={title}
            />
          </label>
          {editor ? (
            <FormattingToolbar
              disabled={save.isPending || invalid || taskOpen}
              editor={editor}
            />
          ) : null}
          <details className="knowledge-insert">
            <summary>Einfügen</summary>
            <div className="knowledge-insert-options">
              <Button
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
                size="sm"
                variant="secondary"
              >
                Material aus Ablage verknüpfen
              </Button>
            </div>
          </details>
        </div>
      ) : null}
      {editing && !taskOpen && !invalid && !save.isPending && materialOpen ? (
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
      ) : null}
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
      <article className={editing ? "doc is-editing" : "doc"}>
        <EditorContent editor={editor} />
      </article>
      {saved && (
        <p className="small subtle" role="status">
          Gespeichert.
        </p>
      )}
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
            savedContent.current = result.page.content;
            setRevision(result.page.revision);
            setSavedTitle(result.page.title);
            setTitle(result.page.title);
            setEmpty(isEmptyContent(result.page.content));
            setDirty(false);
            setSaved(true);
            return result.task;
          }}
        />
      )}
      <aside className="doc-meta small subtle">
        <History aria-hidden="true" size={13} />
        Fassung {revision}
        {" · "}
        {action
          ? `Lesen: Mitglieder der Aktion „${action}“`
          : "Lesen: Personen mit Freigabe"}
        {canEdit
          ? says(address, " · Du kannst bearbeiten", " · Sie können bearbeiten")
          : ""}
      </aside>
      <Modal
        description={savedTitle}
        onClose={() => setAccessOpen(false)}
        open={accessOpen}
        size="lg"
        title="Freigaben verwalten"
      >
        {accessOpen ? (
          <AccessMembersPanel
            actionScoped={!!page.actionId}
            objectId={page.id}
            source={pageMemberSource(client, page.id)}
          />
        ) : null}
      </Modal>
      {discardDialog}
    </div>
  );
}

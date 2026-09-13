import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Node } from "@tiptap/core";
import {
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  useEditorState,
  type NodeViewProps,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button, StatusMessage } from "@leonaid/ui";
import type { ModulePageContext } from "../modules";
import "./knowledge.css";

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
          canEdit={rights.data.canEdit && !page.error && !rights.error}
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
  page,
  canEdit,
  basePath,
  reload,
}: {
  client: LeonAidApiClient;
  page: Page;
  canEdit: boolean;
  basePath: string;
  reload: () => Promise<void>;
}) {
  const [title, setTitle] = useState(page.title);
  const [savedTitle, setSavedTitle] = useState(page.title);
  const [revision, setRevision] = useState(page.revision);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const operation = useRef(crypto.randomUUID());
  const extensions = useMemo(
    () => [
      StarterKit.configure({
        underline: false,
        trailingNode: false,
        link: {
          openOnClick: false,
          autolink: false,
          linkOnPaste: false,
          isAllowedUri: (url) => /^https?:\/\//i.test(url),
        },
      }),
      taskReference(client, basePath),
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
      attributes: {
        role: "textbox",
        "aria-label": "Seiteninhalt",
        "aria-multiline": "true",
        class: "knowledge-document",
      },
    },
  });
  const state = useEditorState({
    editor,
    selector: ({ editor: current }) => ({
      bold: current?.isActive("bold") ?? false,
      italic: current?.isActive("italic") ?? false,
      bullet: current?.isActive("bulletList") ?? false,
      heading: current?.isActive("heading", { level: 2 }) ?? false,
    }),
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
    editor?.setEditable(canEdit && !save.isPending && !invalid, false);
  }, [editor, canEdit, save.isPending, invalid]);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  return (
    <>
      <header>
        <h1 id="page-heading">{savedTitle}</h1>
        <p>
          Version {revision}
          {!canEdit ? " · Nur lesen" : ""}
        </p>
      </header>
      {canEdit && (
        <label>
          Seitentitel
          <input
            maxLength={240}
            required
            value={title}
            disabled={save.isPending}
            onChange={(event) => {
              setTitle(event.target.value);
              changed();
            }}
          />
        </label>
      )}
      {invalid && (
        <StatusMessage tone="error">
          <p>
            Dieser Inhalt kann nicht vollständig dargestellt werden. Speichern
            ist gesperrt, damit nichts verloren geht.
          </p>
        </StatusMessage>
      )}
      {canEdit && (
        <div
          className="knowledge-toolbar"
          role="group"
          aria-label="Textformatierung"
        >
          <Button
            variant="secondary"
            disabled={!editor || save.isPending || invalid}
            aria-pressed={state?.bold}
            onClick={() => editor?.chain().focus().toggleBold().run()}
          >
            Fett
          </Button>
          <Button
            variant="secondary"
            disabled={!editor || save.isPending || invalid}
            aria-pressed={state?.italic}
            onClick={() => editor?.chain().focus().toggleItalic().run()}
          >
            Kursiv
          </Button>
          <Button
            variant="secondary"
            disabled={!editor || save.isPending || invalid}
            aria-pressed={state?.heading}
            onClick={() =>
              editor?.chain().focus().toggleHeading({ level: 2 }).run()
            }
          >
            Überschrift
          </Button>
          <Button
            variant="secondary"
            disabled={!editor || save.isPending || invalid}
            aria-pressed={state?.bullet}
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
          >
            Aufzählung
          </Button>
          <Button
            variant="secondary"
            disabled={!editor || save.isPending || invalid}
            onClick={() => editor?.chain().focus().undo().run()}
          >
            Rückgängig
          </Button>
          <Button
            variant="secondary"
            disabled={!editor || save.isPending || invalid}
            onClick={() => editor?.chain().focus().redo().run()}
          >
            Wiederholen
          </Button>
        </div>
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
      {canEdit && (
        <div className="knowledge-toolbar">
          <Button
            disabled={
              !editor || !dirty || !title.trim() || save.isPending || invalid
            }
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Wird gespeichert …" : "Speichern"}
          </Button>
          <Button
            variant="secondary"
            disabled={save.isPending}
            onClick={() => void reload()}
          >
            Aktuelle Version laden
          </Button>
        </div>
      )}
    </>
  );
}

import { useState } from "react";
import type { Editor } from "@tiptap/core";
import { useEditorState } from "@tiptap/react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  TextBoldIcon,
  TextItalicIcon,
  TextUnderlineIcon,
  TextStrikethroughIcon,
  LeftToRightListBulletIcon,
  LeftToRightListNumberIcon,
  TextAlignLeftIcon,
  TextAlignCenterIcon,
  TextAlignRightIcon,
  UndoIcon,
  RedoIcon,
  Link01Icon,
} from "@hugeicons/core-free-icons";

export function FormattingToolbar({
  editor,
  disabled,
  compact = false,
}: {
  editor: Editor;
  disabled: boolean;
  compact?: boolean;
}) {
  const [linkOpen, setLinkOpen] = useState(false);
  const [href, setHref] = useState("");
  const [linkError, setLinkError] = useState("");
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      underline: e.isActive("underline"),
      strike: e.isActive("strike"),
      bullet: e.isActive("bulletList"),
      ordered: e.isActive("orderedList"),
      heading: e.isActive("heading")
        ? String(e.getAttributes("heading").level)
        : "0",
      family: e.getAttributes("textStyle").fontFamily ?? "",
      size: e.getAttributes("textStyle").fontSize ?? "",
      align:
        e.getAttributes(e.isActive("heading") ? "heading" : "paragraph")
          .textAlign ?? "left",
      link: e.isActive("link"),
      undo: e.can().undo(),
      redo: e.can().redo(),
    }),
  });
  const action = (
    label: string,
    icon: typeof TextBoldIcon,
    run: () => void,
    active?: boolean,
    unavailable = false,
  ) => (
    <button
      type="button"
      className="knowledge-tool"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled || unavailable}
      onClick={run}
    >
      <HugeiconsIcon icon={icon} size={18} aria-hidden="true" />
    </button>
  );
  return (
    <div
      className={
        compact
          ? "knowledge-formatting knowledge-formatting--compact"
          : "knowledge-formatting"
      }
    >
      <div
        className="knowledge-formatting-row"
        role="toolbar"
        aria-label={compact ? "Auswahl formatieren" : "Textformatierung"}
      >
        {!compact && (
          <>
            <select
              aria-label="Absatzformat"
              value={state.heading}
              disabled={disabled}
              onChange={(e) => {
                const level = Number(e.target.value);
                const chain = editor.chain().focus();
                if (level === 0) chain.setParagraph().run();
                else
                  chain
                    .setHeading({ level: level as 1 | 2 | 3 | 4 | 5 | 6 })
                    .run();
              }}
            >
              <option value="0">Normaler Text</option>
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  Überschrift {n}
                </option>
              ))}
            </select>
            <select
              aria-label="Schriftart"
              value={state.family}
              disabled={disabled}
              onChange={(e) =>
                e.target.value
                  ? editor.chain().focus().setFontFamily(e.target.value).run()
                  : editor.chain().focus().unsetFontFamily().run()
              }
            >
              <option value="">Standardschrift</option>
              <option value="sans-serif">Sans Serif</option>
              <option value="serif">Serif</option>
              <option value="monospace">Monospace</option>
            </select>
            <select
              aria-label="Schriftgröße"
              value={state.size}
              disabled={disabled}
              onChange={(e) =>
                e.target.value
                  ? editor.chain().focus().setFontSize(e.target.value).run()
                  : editor.chain().focus().unsetFontSize().run()
              }
            >
              <option value="">Standardgröße</option>
              {[12, 14, 16, 18, 20, 24, 32].map((n) => (
                <option key={n} value={`${n}px`}>
                  {n} px
                </option>
              ))}
            </select>
          </>
        )}
        <span className="knowledge-tool-group">
          {action(
            "Fett",
            TextBoldIcon,
            () => editor.chain().focus().toggleBold().run(),
            state.bold,
          )}
          {action(
            "Kursiv",
            TextItalicIcon,
            () => editor.chain().focus().toggleItalic().run(),
            state.italic,
          )}
          {action(
            "Unterstreichen",
            TextUnderlineIcon,
            () => editor.chain().focus().toggleUnderline().run(),
            state.underline,
          )}
          {action(
            "Durchstreichen",
            TextStrikethroughIcon,
            () => editor.chain().focus().toggleStrike().run(),
            state.strike,
          )}
          {action(
            "Link bearbeiten",
            Link01Icon,
            () => {
              setHref(editor.getAttributes("link").href ?? "");
              setLinkError("");
              setLinkOpen(!linkOpen);
            },
            state.link,
          )}
        </span>
        {!compact && (
          <>
            <span className="knowledge-tool-group">
              {action(
                "Aufzählung",
                LeftToRightListBulletIcon,
                () => editor.chain().focus().toggleBulletList().run(),
                state.bullet,
              )}
              {action(
                "Nummerierte Liste",
                LeftToRightListNumberIcon,
                () => editor.chain().focus().toggleOrderedList().run(),
                state.ordered,
              )}
              <button
                type="button"
                className="knowledge-tool"
                disabled={disabled || !editor.can().sinkListItem("listItem")}
                onClick={() =>
                  editor.chain().focus().sinkListItem("listItem").run()
                }
              >
                Einrücken
              </button>
              <button
                type="button"
                className="knowledge-tool"
                disabled={disabled || !editor.can().liftListItem("listItem")}
                onClick={() =>
                  editor.chain().focus().liftListItem("listItem").run()
                }
              >
                Ausrücken
              </button>
            </span>
            <span className="knowledge-tool-group">
              {action(
                "Linksbündig",
                TextAlignLeftIcon,
                () => editor.chain().focus().setTextAlign("left").run(),
                state.align === "left",
              )}
              {action(
                "Zentriert",
                TextAlignCenterIcon,
                () => editor.chain().focus().setTextAlign("center").run(),
                state.align === "center",
              )}
              {action(
                "Rechtsbündig",
                TextAlignRightIcon,
                () => editor.chain().focus().setTextAlign("right").run(),
                state.align === "right",
              )}
              <button
                type="button"
                className="knowledge-tool"
                aria-pressed={state.align === "justify"}
                disabled={disabled}
                onClick={() =>
                  editor.chain().focus().setTextAlign("justify").run()
                }
              >
                Blocksatz
              </button>
            </span>
            <span className="knowledge-tool-group">
              {action(
                "Rückgängig",
                UndoIcon,
                () => editor.chain().focus().undo().run(),
                undefined,
                !state.undo,
              )}
              {action(
                "Wiederholen",
                RedoIcon,
                () => editor.chain().focus().redo().run(),
                undefined,
                !state.redo,
              )}
            </span>
          </>
        )}
      </div>
      {linkOpen && (
        <form
          className="knowledge-link-form"
          onSubmit={(e) => {
            e.preventDefault();
            try {
              const url = new URL(href);
              if (!["https:", "http:"].includes(url.protocol))
                throw new Error();
              editor
                .chain()
                .focus()
                .extendMarkRange("link")
                .setLink({ href: url.href })
                .run();
              setLinkOpen(false);
            } catch {
              setLinkError(
                "Bitte eine vollständige Adresse mit https:// oder http:// eingeben.",
              );
            }
          }}
        >
          <label>
            Link-Adresse
            <input
              type="url"
              required
              value={href}
              onChange={(e) => setHref(e.target.value)}
            />
          </label>
          <button type="submit" className="knowledge-tool" disabled={disabled}>
            Link übernehmen
          </button>
          <button
            type="button"
            className="knowledge-tool"
            disabled={disabled}
            onClick={() => {
              editor.chain().focus().extendMarkRange("link").unsetLink().run();
              setLinkOpen(false);
            }}
          >
            Link entfernen
          </button>
          <button
            type="button"
            className="knowledge-tool"
            onClick={() => {
              setLinkOpen(false);
              editor.commands.focus();
            }}
          >
            Schließen
          </button>
          {linkError && <p role="alert">{linkError}</p>}
        </form>
      )}
    </div>
  );
}

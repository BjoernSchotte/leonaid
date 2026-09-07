/** Gettext-style host translation. Values are text, never HTML. */
export type EditorTranslator = (
  message: string,
  values?: Readonly<Record<string, string | number>>,
) => string;

/** Also use this as the fallback for messages missing from a host catalogue. */
export const formatEditorMessage: EditorTranslator = (message, values = {}) =>
  message.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (placeholder, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : placeholder,
  );

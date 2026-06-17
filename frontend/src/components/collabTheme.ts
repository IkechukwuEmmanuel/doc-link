import { EditorView } from "@codemirror/view";

/** Maps CodeMirror 6 onto SpacePad's design tokens so the editor surface is
    visually continuous with the homepage hero textarea. */
export const editorTheme = EditorView.theme({
  "&": {
    color: "var(--color-text-primary)",
    backgroundColor: "transparent",
    fontFamily: "var(--font-sans)",
    fontSize: "var(--text-md)",
    lineHeight: "var(--leading-read)",
    height: "100%",
  },
  ".cm-content": {
    padding: "0",
    caretColor: "var(--color-accent)",
  },
  ".cm-scroller": {
    fontFamily: "var(--font-sans)",
    lineHeight: "var(--leading-read)",
  },
  "&.cm-focused": {
    outline: "none",
  },
  ".cm-line": {
    padding: "0",
  },
  ".cm-cursor": {
    borderLeftColor: "var(--color-accent)",
  },
  ".cm-placeholder": {
    color: "var(--color-text-muted)",
  },
});

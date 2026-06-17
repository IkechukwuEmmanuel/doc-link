# DESIGN_DECISIONS.md

Companion to `DECISIONS.md`, logging UI/UX design-track choices per the design
spec §6. Functional/architecture decisions live in `DECISIONS.md`.

## Typeface & sourcing
- **Sans (UI + editor):** Inter (variable), self-hosted via `@fontsource-variable/inter`.
- **Mono (slug/URL, code, `/raw`):** JetBrains Mono, self-hosted via `@fontsource/jetbrains-mono`.
- Both are bundled by Vite from npm — **no external/unapproved CDN**, satisfying the
  spec's "self-hosted or approved CDN" requirement.

## Theme
- Light + dark both implemented as CSS custom properties in `src/styles/tokens.css`.
- First visit respects `prefers-color-scheme`; manual toggle persists to
  `localStorage` (`spacepad-theme`). Account-level persistence lands with auth (Phase 4).
- Neither bg is pure white/black per spec (light `#fafafa`, dark `#16161c`).

## Presence color palette (final)
Separate from the brand palette. 10 evenly-spaced hues, **red and amber deliberately
excluded** so presence never reads as danger/warning. Defined in `src/styles/presence.ts`,
assigned round-robin per session:
`indigo, sky, teal, emerald, lime, violet, fuchsia, pink, cyan, blue`.
Selections render at ~18% opacity of the peer's solid color. (Live wiring: Phase 2.)

## Dashboard layout choice
- **Deferred to Phase 5** (the dashboard screen isn't built yet). Provisional intent:
  **table** layout, per the spec's own lean ("more information-dense and appropriate
  for this audience"). Will be confirmed when built.

## Continuous homepage → pad transition
- The homepage central element is a borderless auto-growing `<textarea>` that *is* the
  create action (click or first keystroke). Typed/seeded text is carried into the new
  pad via router state (`{ seed }`) and saved immediately, so the empty→full transition
  is client-routed with no full reload and no loading spinner (spec §0 tertiary, §2.1, §5).
- True single-DOM-element morph (literally reusing the same node restyled across the
  route change) is approximated rather than pixel-perfect: the homepage and editor are
  separate routes sharing identical typography/caret tokens, so the visual handoff is
  continuous. Logged as a conscious approximation, not a violation.

## Components built once, reused (spec §6)
`CopyButton`, `TopBar`, `PresenceStack`, `ConnectionIndicator`, `ThemeToggle` live in
`src/components/`. The file/image chip is specified but lands with Phase 3.

## Editor surface (Phase 2)
- The Phase 1 `<textarea>` is replaced by **CodeMirror 6** (`src/components/CollabEditor.tsx`)
  bound to a Yjs doc via `y-codemirror.next` + `y-websocket`. CodeMirror was chosen over
  keeping the textarea because in-text remote cursors/selections (design spec §2.2) are
  not renderable in a plain textarea. The editor theme (`collabTheme.ts`) maps CM6 onto
  the existing design tokens so the homepage→pad typography handoff stays continuous.
- **Remote cursors/selections** render via `yCollab` using the presence palette
  (`presence.ts`). Peer color is assigned per browser session (stable across reloads via
  `sessionStorage`) and shared through Yjs awareness.
- **`PresenceStack` and `ConnectionIndicator` are now live**: peers come from awareness
  state; the connection indicator reflects the real `WebsocketProvider` status
  (`connected` → silent, `disconnected` → "Reconnecting…", re-`connected` → "Reconnected").
- The per-keystroke REST save + "Saving…/Saved" indicator is removed; persistence is now
  the server-side debounced CRDT flush, so the indicator would be redundant.

## Anti-patterns (spec §5)
- None violated. No spinners on the homepage→pad transition, no modals, no toasts,
  no onboarding, no mascot. Connection status and copy confirmation are ambient/inline.

## Phase-1 scope note
This pass restyles the surfaces that exist in Phase 1 (homepage + pad editor + state
screens) to the design system. The editor is still a plain `<textarea>`; the
WYSIWYG-markdown Tiptap surface, remote cursors, presence, drag-drop upload UI, login/
signup, and dashboard are built in their respective PRD phases on top of these tokens
and components.

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

## Dashboard layout choice (Phase 5 — final)
- **Table** layout, per the spec's own lean ("more information-dense and appropriate for
  this audience"). Built and confirmed final in Phase 5 — the earlier "provisional"
  qualifier no longer applies. Columns: name/slug, last edited, visibility, size, actions
  (`AccountPads.tsx`).
- **Name vs slug display rule** (spec §2): a renamed pad shows its custom name with the
  `/slug` trailing in muted mono; a never-renamed pad shows the slug itself in mono. So a
  pad always has a stable, scannable identity whether or not it's been named.
- **Last-edited** uses relative time (`Intl.RelativeTimeFormat`) with the full timestamp on
  `title` hover (`format.ts`).

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
`src/components/`.

## File chip + upload (Phase 3)
- `FileTray` (`src/components/FileTray.tsx`) sits below the editor: a click/drag-drop
  dropzone plus a row of file chips. No modal — uploads are inline and ambient, per the
  anti-pattern rules.
- **Chips encode scan state** rather than hiding unscanned files: `clean` chips are a
  monospace download link with size; `pending` shows "scanning…" (warning color);
  `failed` shows the name struck-through with "unavailable" (danger color) and a tooltip
  explaining it failed the malware scan. This keeps the security state visible instead of
  silently dropping files.
- Styling uses existing tokens (pill radius, surface/border, mono for filenames) so the
  tray reads as part of the same system.

## Auth screens + signed-in TopBar (Phase 4)
- `/login` and `/signup` share one `AuthPage` component (a single card, no modal) with
  email/password fields and a "Continue with Google" button. Minimal and token-styled,
  consistent with the no-onboarding/no-mascot rules.
- The TopBar now reflects session state: when signed out it keeps the dismissible
  "Sign in to keep this pad forever" hint; when signed in it shows the display name (or
  email) + a "Log out" action and hides the hint.
- **Claim affordance**: a logged-in user viewing an unowned pad sees a "Claim this pad"
  pill in the TopBar. It disappears once the pad has an owner. This surfaces the new
  ownership capability inline rather than via a separate management screen (that's
  Phase 5).

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

## Dashboard inline controls (Phase 5)
- **No modals — all inline**, keeping the "Anti-patterns" record below intact.
  - **Rename** (§4.4): the name cell becomes an input in place; Enter/blur commits, Escape
    reverts.
  - **Visibility** (§4.3): the visibility cell is a button (current state + glyph) that
    opens a small inline `role=menu` of the three options directly under it — not a modal,
    not a separate page.
  - **Archive / delete** (§4.5): delete swaps the row's action cluster for an inline
    "Delete? Yes / No" confirmation; archive/unarchive is a single inline action that drops
    the row from the current view. Edits apply optimistically for immediacy.
- **Hover-revealed actions with a keyboard/touch equivalent.** Row actions are real
  `<button>`s always present in the DOM, revealed on `:hover`/`:focus-within` and shown
  unconditionally on touch (`@media (hover: none)`) — the tap-and-hold/kebab fallback the
  spec §2 calls for, and a precondition for the accessibility pass.

## Signed-in TopBar — "My Pads" (Phase 5)
- The signed-in TopBar (from Phase 4) gains a **"My Pads"** link to `/account/pads`,
  sitting alongside the display name + "Log out". The signed-out hint and Claim affordance
  are unchanged — this extends the Phase 4 state rather than replacing it.

## Read-only & no-access surfaces (Phase 5)
- A pad the viewer may read but not edit renders as a **static read-only surface** (escaped
  text, no editor chrome) instead of the live collaborative editor — viewers don't open the
  write socket at all.
- **`ConnectionIndicator` gains a distinct `noaccess` state.** A permission rejection (WS
  close 4403) must not look like a network drop: it reads "View-only — no edit access" in
  the warning color, never the pulsing "Reconnecting…". A pad the user can't read at all
  (REST 403) gets its own full state screen ("This pad is private").

## Account recovery screens (Phase 7)
- `/forgot-password`, `/reset-password`, `/verify-email` reuse the single `auth-card`
  pattern (no modal, token-styled), consistent with the Phase 4 auth screens. The reset
  request screen always shows the same "if an account exists…" confirmation — the UI mirrors
  the backend's no-existence-oracle stance.

## PIN-protected pads (Supabase + PIN phase)
- **Locked-pad screen, not a modal or wall.** When `GET /api/pads/{slug}` returns
  `locked: true`, the pad route renders a calm on-brand screen reusing the `auth-card`
  pattern (`Pad.tsx` `LockedPad`): a short "This pad is locked" line, the `/slug` in muted
  mono, and a single PIN field + submit. It reads as part of the editor chrome, not a
  jarring interruption — consistent with the no-modal anti-pattern record below.
- **Input adapts to `pin_format`.** A numeric PIN uses `inputMode="numeric"` +
  `pattern="[0-9]*"` (keypad on mobile); an alphanumeric passcode uses a plain text input.
  The field is `type="password"` either way so a shoulder-surfer can't read it.
- **Two distinct inline error states (not one, not a toast).** A wrong PIN shows the
  backend's inline "Incorrect PIN" message (`role="alert"`), matching the auth-page
  validation pattern. A rate-limited 429 shows a *different* message — "Too many attempts,
  try again in about N minute(s)" derived from `Retry-After` — and disables the input until
  then, so a lockout never masquerades as a typo.
- **No persistent "unlocked" banner.** Once unlocked, the pad behaves like any accessible
  pad for the window; the existing connection/access-state indicators carry the state. We
  deliberately did not add an always-on "you are unlocked" element for a background concern.
- **Dashboard PIN toggle, orthogonal to visibility.** In `AccountPads.tsx` the inline
  controls gain a PIN affordance (add / set format numeric|alphanumeric / remove) alongside
  the visibility control. It is **hidden when `private` is selected**, mirroring the
  server-side mutual-exclusion rule (`private` is a stronger gate) so the UI can't offer an
  invalid combined state.

## Anti-patterns (spec §5)
- Still none violated. No spinners on the homepage→pad transition, no modals (dashboard
  inline controls included), no toasts, no onboarding, no mascot. Connection status, copy
  confirmation, and all dashboard edits are ambient/inline.

## Phase-8 – Frontend feature additions

### 6.1 Locked-pad screen – visual rework
- **Background animation** – chose an SVG “wavy line” field with `stroke-dasharray` animation (non‑WebGL, respects `prefers-reduced-motion`).
- **Auto-submit on PIN length** – numeric PINs auto-submit when they reach 4‑6 digits; the `Enter` key still provides explicit submit for alphanumeric PINs.
- **Inline visual error** – the input shakes + turns danger colour; the message appears below without a modal or toast.

### 6.2 Five-theme system
- Implemented five named themes (`oxidized-copper`, `walnut-ink`, `storm-slate`, `white`, `black`) as CSS custom property suffixes (`[data-theme="oxidized-copper"]`, etc.).
- Each theme has its own light/dark variant set in `tokens.css`.
- **Homepage auto‑rotation** – time‑of‑day bands map to themes. Location (timezone) serves as a tie‑breaker.
- **Manual pick overrides** – stored in `localStorage` under `spacepad-theme`; persists across visits.

### 6.3 Hidden formatting panel in editor
- **Reveal mechanism** – `Ctrl+Shift+F` keyboard shortcut. The panel never appears on hover or click to prevent accidental activation.
- **Persistence scope** – per‑pad stored values in `localStorage` (`collabFormatting` JSON) so formatting choices travel with the browser session.
- **Decision** – picked per‑pad persistence because it avoids extra back‑end writes and keeps the UX lightweight. Flagged in `DECISIONS.md`.

### 6.4 Constrained editor page width
- Added a `<select>` in the top‑bar (`Width` control) for **Narrow / Standard / Wide**.
- Presets applied via CSS variable `--canvas-max-width` (Narrow = 600 px, Standard = 740 px, Wide = 1024 px).
- Preference persisted in `localStorage` under `spacepad-editor-width`.

### 6.5 Side display for uploaded media
- Implemented a right‑hand side panel (`.pad-file-side`) that houses the existing `FileTray`.
- Responsive fallback: on viewports `< 768 px` the side panel collapses to `width: 100 %` and stacks under the editor.
- No new back‑end endpoints required – `FileTray` already lists/removes files via existing API.

### 6.6 `/new` anonymous pad creation route
- Routes to a lightweight component (`NewPad.tsx`) that runs `createPad()` and redirects to the new slug.
- Mirrors the homepage’s “instant‑create” flow without extra intermediate screen.

### 6.7 Copy button – full URL
- Changed the `CopyButton` value from just `slug` to `${origin}/${slug}` to copy the shareable full URL.
- No back‑end changes; purely client-side.

## Trade-offs documented

- **Auto-rotating homepage theme** – means the landing page does not have a single canonical appearance. Documented as an intentional trade‑off.
- **Per-pad formatting persistence** – stored locally; no account-level preference introduced to keep Phase-8 scope minimal.
- **Side panel collapse on mobile** – chosen over a persistent off-canvas drawer for simplicity and accessibility (keyboard focus still reaches actions).
This pass restyles the surfaces that exist in Phase 1 (homepage + pad editor + state
screens) to the design system. The editor is still a plain `<textarea>`; the
WYSIWYG-markdown Tiptap surface, remote cursors, presence, drag-drop upload UI, login/
signup, and dashboard are built in their respective PRD phases on top of these tokens
and components.

## URL scheme & usernames
- **Usernames in top-level namespace:** Usernames are case-insensitive (stored normalized)
  but displayed as entered. They occupy the same top-level URL space as pads and reserved
  routes, sharing the reserved-word list to prevent routing conflicts (e.g. a username of
  `new` would be ambiguous with the creation route).
- **Three address formats coexist:**
  - `/{slug}` for anonymous pads (existing, unchanged behavior).
  - `/{username}/{padname}` for owned pads, where padname is the slug or custom name.
  - `/new` (global), `/{username}/new`, `/{username}/new/{custom-name}` for creation.
    The `/new` catch-all is routed at the frontend (any URL ending in `/new` is treated
    as a creation request); the backend does not special-case it.
- **Claiming and renaming redirect:** When an anonymous pad is claimed (gains an owner),
  accessing the old `/{slug}` returns a 301 redirect to `/{username}/{slug}`. Similarly,
  when an owned pad is renamed, the old `/{username}/{old-name}` address redirects to the
  new one. This preserves existing links and bookmarks across ownership and name changes.
- **Rename changes the address (design pivot):** The original Phase-5 dashboard spec treated
  custom names as display-only, not affecting the underlying pad address. The new URL scheme
  makes custom names **the actual address**, so renaming now changes the pad's URL. This is
  intentional, and redirects ensure old links don't break. Documented as a deliberate
  decision change in `DECISIONS.md`.


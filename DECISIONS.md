# DECISIONS.md

This file logs implementation choices made by the build agent where the PRD was
ambiguous or left a decision open, plus any pre-launch blockers. Per the PRD §0,
ambiguities are resolved toward the simplest, most boring, production-safe option.

## Conventions
- Each entry: **Context → Decision → Rationale**.
- Pre-launch blockers are flagged with **⚠️ BLOCKER**.

---

## Infrastructure & tooling

**Local stack via Docker Compose.** Postgres 16, Redis 7, and MinIO (S3-compatible)
run via `docker-compose.yml`. MinIO is defined from the start though only used from
Phase 3, so infra stays stable across phases.

**Virus scanning (ClamAV).** ⚠️ BLOCKER (interface implemented in Phase 3; real
scanner still required before launch): The PRD requires all uploads to be
malware-scanned before being retrievable. As of Phase 3 the scan interface
(`app/services/scan.py`) is implemented and **fails closed** — when ClamAV is
disabled or unreachable, uploads are marked `failed` (never `clean`), their bytes are
deleted from storage, and downloads return 409. A real ClamAV daemon is used when
`CLAMAV_ENABLED=true` and reachable (`docker compose --profile scan up -d clamav`).
The remaining launch task is to run ClamAV in production and flip `CLAMAV_ENABLED`;
the fail-closed default guarantees nothing unscanned is ever served in the meantime.

## Backend

**Package manager: pip + `pyproject.toml`** with a pinned `requirements.txt` for
reproducible installs. Boring and universally supported.

**SQLAlchemy 2.x async + asyncpg + Alembic**, per PRD §6.1.

**Slug generation:** `{adjective}-{noun}-{NN}` with a 2-digit zero-padded number
(10–99 → actually 00–99). Word lists are curated and profanity-filtered. On collision,
regenerate (bounded retries) before widening the number range.

---

(Phase-by-phase entries appended below as the build proceeds.)

### Phase 1 — Core pad CRUD + slugs
- Pad content stored as a plain `content` TEXT column in Phase 1 (no CRDT yet, per
  PRD phasing). Phase 2 introduces `crdt_snapshot` (bytea) and the WebSocket layer;
  the Phase 1 plain-text path remains as the REST save-on-debounce fallback.
- "Visiting a non-existent valid slug" returns a 404 with a `creatable: true` flag so
  the frontend can show the "create it?" prompt, rather than auto-creating (PRD §5.1).
- Reserved slugs and format validation enforced at the API boundary (Pydantic + a
  validator), independent of the future profanity job in Phase 6.

### Phase 2 — Real-time collaboration (Yjs/CRDT)
- **CRDT server runs in-process in FastAPI** via `pycrdt` + `pycrdt-websocket`
  (a y-websocket-compatible server), rather than a separate Node sidecar. Keeps the
  stack to one runtime and one persistence path. WebSocket endpoint:
  `WS /api/pads/{slug}/ws` (`app/api/ws.py`); one Yjs room per slug.
- **One `Text` named `content` per doc.** On first open a room is seeded from
  `crdt_snapshot` if present, else from the Phase 1 plain `content` column (legacy
  migration path). Changes are flushed on a 1s debounce back to **both**
  `crdt_snapshot` (+ `crdt_snapshot_updated_at`) **and** the plain `content` column,
  so REST `GET`/`PUT`/`/raw` keep working unchanged (`app/services/crdt.py`).
- **No DB migration needed** — `crdt_snapshot`/`crdt_snapshot_updated_at` were
  pre-provisioned in the initial schema.
- **Redis not required in Phase 2.** Single-process in-memory rooms are sufficient;
  multi-node fan-out (Redis pub/sub or a y-redis store) is deferred to scaling work
  in Phase 6.
- **REST `PUT` retained** as the documented save fallback; the live path is now the
  WebSocket. The frontend no longer calls `PUT` on keystroke but `savePad()` remains
  in the API client.

### Phase 3 — File uploads
- **Uploads are proxied through FastAPI**, not direct-to-MinIO presigned PUTs. The
  scan-before-serve requirement needs a server step regardless, so proxying keeps cap
  enforcement and scanning in one place. `aioboto3` talks to MinIO/S3
  (`app/services/storage.py`).
- **`files` table** (`app/models/file.py`): `pad_id` FK (CASCADE), filename,
  content_type, size, unique `storage_key` (`{pad_id}/{uuid}`), and a `scan_status`
  enum (`pending`/`clean`/`failed`). New Alembic migration `dcd7e589eb1b`. (Note: the
  models for the pre-existing `pads.is_archived`/`pads.name`/`users.display_name`
  columns are not yet defined, so autogenerate proposed dropping them — those drops
  were removed from the migration by hand. Reconciling those columns with their models
  is follow-up work for the phase that uses them.)
- **Caps**: anonymous-tier limits from `Settings` are applied to every pad for now
  (per-file, per-pad count, per-pad total). Authenticated-tier caps land with Phase 4.
- **Scanning fails closed** (see the ClamAV blocker entry above). On a non-clean
  verdict the stored object is deleted immediately; the row is kept as `failed` so the
  UI can show why the file is unavailable.
- **Downloads stream through the backend** (clean-only) rather than via presigned GET,
  so the clean-status gate is enforced on every fetch, not just at URL-issue time.

### Phase 4 — Authentication
- **Token delivery**: refresh token in a `Secure`/`httpOnly`/`SameSite=Lax` cookie
  scoped to `/api/auth`; access token (15 min) returned in the JSON body and kept in
  memory by the SPA. This is the XSS-resistant default — the long-lived credential is
  never readable by JS, and the short-lived one dies with the tab. `cookies_secure` is
  off in `development` so it works over http locally.
- **Password hashing**: argon2 (`argon2-cffi`), not bcrypt — modern default, no length
  cap surprises. JWTs are HS256 via `pyjwt` with a typed `type` claim so an access
  token can't be replayed as a refresh token (enforced + tested).
- **Refresh rotation**: every `/refresh` issues a fresh refresh cookie. A server-side
  token denylist/rotation-family is deferred (no token storage yet); acceptable for now
  given short access TTL and httpOnly refresh.
- **Google OAuth**: standard auth-code flow; `upsert_google_user` links by email and
  marks `email_verified`. The redirect_uri points at the frontend origin so the Vite
  proxy forwards `/api/auth/google/callback` to the backend in dev. Live round-trip
  needs real client credentials and is unverified here (unit-tested with a mocked
  exchange).
- **Claiming**: `POST /api/pads/{slug}/claim` (auth required) sets `owner_id` and
  `is_anonymous=false` only if the pad is currently unowned (409 otherwise). This is the
  first real use of the long-dormant `owner_id` column. Visibility enforcement stays in
  Phase 5.
- **Model drift partially closed**: added `User.display_name` (column existed since
  migration `610b7d4ad610`). `pads.is_archived`/`pads.name` remain model-less until the
  phase that uses them (Phase 5).

### Phase 5 — Authenticated features
- **Phase 5 data model completion → Decision**: Add `name` and `is_archived` columns to the `Pad` model (already present in DB) and create the `PadCollaborator` model with `viewer`/`editor` roles, `invited_at`, `accepted_at`, and a unique constraint on (`pad_id`, `user_id`). Rationale: Brings the ORM in sync with the existing DB schema, enables collaborator management and pad metadata needed for the dashboard and fine‑grained access control.
- **Visibility enforcement choice**: For private pads, `GET /api/pads/{slug}` returns 403 (not 404) when the user lacks access. This reveals existence but not content, matching the principle that private pads are "unlisted" rather than "hidden". WebSocket connections to private rooms are rejected with close code 4403 before any CRDT state is exchanged.
- **Collaborator invite flow**: `POST /api/pads/{slug}/collaborators` accepts `{ email, role }` and creates a `PadCollaborator` row immediately if the email matches an existing user. If no matching user exists, returns 422 (out of scope for v1 per PRD §5.5). No separate "accept invite" step in v1.
- **Pad management endpoints**: `PATCH /api/pads/{slug}` handles metadata updates (name, visibility, is_archived) separately from content updates (`PUT`). This separation keeps auth rules clear: metadata changes are owner-only, while content writes follow visibility rules. `DELETE /api/pads/{slug}` hard-deletes with cascade to files and collaborators.
- **Dashboard route**: `/account/pads` added to router, gated by auth check using existing `AuthProvider` session state. Redirects to `/login` if no session.
- **Table layout confirmed**: Using table layout for the dashboard (not provisional) as it provides the information-dense view appropriate for this audience.
- **Inline controls**: Rename, visibility, archive/delete all use inline controls without modals, consistent with anti-pattern rules.
- **New pad from dashboard**: Authenticated pad creation sets `owner_id` at creation time, no separate claim step needed.

### Phase 5–7 continuation (implementation notes)

**Model/migration reconciliation.** The `Pad.name` column is `String(120)` to match
the pre-existing migration `726857c6f636` (the model had drifted to 255). The
`PadCollaborator` unique constraint is named `uq_pad_collaborator_pad_user` to match
migration `e5f8b2c3d4a1`. Two new migrations were added on the existing linear chain:
`f1a2b3c4d5e6` (`pads.cold_storage_eligible`, Phase 6) and `a7b8c9d0e1f2`
(`email_tokens`, Phase 7). `alembic heads` is a single head.

**Access-control single source of truth.** `app/services/access.py` holds the
read/write rules (`can_read`, `can_write_content`, `is_owner`). Both the REST layer
(`api/pads.py`) and the WS layer (`api/ws.py` → `authorize_ws`) call it, so there is
exactly one place the visibility matrix lives. Content writes (`PUT`, live WS) follow
the visibility rules; metadata writes (`PATCH`, `DELETE`, collaborator management) are
owner-only, checked separately.

**WebSocket auth transport → query param.** The access token is read from the `?token=`
query parameter on the WS handshake, because a browser WebSocket cannot set an
`Authorization` header and y-websocket appends connection params to the URL. The gate
runs in `authorize_ws` *before* `websocket.accept()`; rejection closes with code 4403
(no access) / 4404 (bad slug) / 4429 (rate limited) before any CRDT bytes flow. A
viewer (read-only) is intentionally **not** given the live socket — the live channel is
bidirectional and a read-only Yjs room isn't worth the complexity for v1; viewers read
via REST and the frontend renders them a static, read-only surface. Documented so the
"viewer can't join WS" behaviour isn't mistaken for a bug.

**Pad deletion is explicit, not FK-cascade-only.** `delete_pad` removes storage objects,
file rows, and collaborator rows explicitly before deleting the pad, so behaviour is
identical on Postgres and the SQLite test harness (where `ondelete=CASCADE` isn't
enforced without `PRAGMA foreign_keys`) and storage objects are never orphaned.

### Phase 6 — Rate limiting & abuse prevention
- **Token-bucket limiter** (`app/services/ratelimit.py`). Pad creation is guarded by two
  buckets — 10/IP/hour and a 1-per-5-seconds burst — and WS edits by a 60/min/connection
  bucket, matching PRD §5.4. IP keys are a salted SHA-256 (`ip_hash_salt`); raw IPs are
  never stored (PRD §6.4). REST limit → 429 with a `Retry-After` header; WS limit → close
  code 4429 with a human-readable reason the frontend renders distinctly.
- **⚠️ BLOCKER — Redis required at launch (fails open until then).** The limiter enforces
  cross-process via Redis (atomic Lua token bucket). `init()` pings Redis in the app
  lifespan; if Redis is unreachable (or `init()` never ran, as in the ASGI test harness),
  the limiter **fails open** — requests are allowed. Rate limiting is best-effort abuse
  prevention, not a security control, so an infra outage must not take down pad creation.
  The launch task is to run Redis and confirm `init()` wires it (mirrors the ClamAV
  precedent). Tests prove the algorithm + endpoint behaviour by injecting an in-memory
  backend.
- **Cold-storage flagging** (`app/services/coldstorage.py`). A plain async
  `flag_cold_pads()` sets `cold_storage_eligible=True` on pads whose `last_opened_at` is
  older than `cold_storage_after_days` (default 365). Per PRD §5.4 this is a storage-cost
  marker, **not** deletion and **not** user-facing expiry — no "expiring soon" UI exists.
  Driven two ways (the boring option, no new dependency): a cron entry point
  (`python -m app.services.coldstorage`) and an optional in-process daily asyncio loop
  started from the lifespan. APScheduler was deliberately *not* added.

### Phase 7 — Polish & hardening
- **Password reset & email verification** (`api/auth.py`, `services/token.py`,
  `models/token.py`). Single-use, time-boxed tokens (`email_tokens`): only a SHA-256 hash
  is stored, the raw token lives only in the emailed link. Reset TTL is 1 hour (PRD §5.6).
  `consume()` collapses every failure mode (unknown / wrong purpose / expired / used) to a
  single "invalid" result so there's no oracle. Reset *request* always returns 202 and
  never reveals whether an account exists.
- **Email-verified gate on private pads.** `PATCH /api/pads/{slug}` with
  `visibility: private` is rejected (403) unless `user.email_verified` (PRD §5.6). Google
  OAuth users are already verified; password users must complete the verify flow first.
- **⚠️ BLOCKER — no email provider wired.** `app/services/email.py` *logs* messages
  (including the action link) when `EMAIL_PROVIDER` is empty (the default), so reset/verify
  flows are exercisable end-to-end in dev but nothing is actually delivered. The boring
  launch choice is SMTP (works with Postmark/SES/Mailgun, no vendor SDK lock-in); set
  `EMAIL_PROVIDER` + credentials and implement the `send_email` branch. Same stub-and-flag
  precedent as ClamAV.
- **Security review.** CORS is locked to an explicit allowlist (`CORS_ORIGINS`, not `*`)
  with `allow_credentials=True` — verified in `app/main.py`. XSS: there is no raw-HTML
  render path — CodeMirror is plain text, the read-only viewer renders content as an
  escaped React text node, `/raw` is `text/plain`, and the dashboard renders names/slugs
  as text nodes. Confirmed by grep for `dangerouslySetInnerHTML`/`innerHTML` (none).
- **Accessibility.** The dashboard's hover-revealed row actions are always real,
  focus-reachable `<button>`s revealed via `:hover`/`:focus-within` (and always visible on
  touch / `hover: none`), satisfying the keyboard + touch requirement (dashboard spec §2).
  Global `:focus-visible` outline, table header `scope`, `aria-haspopup`/`aria-expanded`
  on the visibility control, `role=menuitemradio` options, and a `.visually-hidden` label
  on the actions column. A full automated axe-core pass against a running instance remains
  a launch-time verification step (no browser harness in this environment).

### Phase-7 & 8 continuation (implementation notes)

**Model/migration reconciliation.** The `Pad.name` column is `String(120)` to match the pre-existing migration `726857c6f636` (the model drifted to 255). The `PadCollaborator` unique constraint is named `uq_pad_collaborator_pad_user` to match migration `e5f8b2c3d4a1`. Two new migrations were added on the existing linear chain:
`f1a2b3c4d5e6` (`pads.cold_storage_eligible`, Phase 6) and `a7b8c9d0e1f2`
(`email_tokens`, Phase 7). `alembic heads` is a single head.

**Access-control single source of truth.** `app/services/access.py` holds the
read/write rules (`can_read`, `can_write_content`, `is_owner`). Both the REST layer
(`api/pads.py`) and the WS layer (`api/ws.py` → `authorize_ws`) call it, so there is exactly one place the visibility matrix lives. Content writes (`PUT`, live WS) follow the visibility rules; metadata writes (`PATCH`, `DELETE`, collaborator management) are owner-only, checked separately.

### Phase-8 – Frontend feature additions

**Locked‑pad screen – visual rework (as per prompt).**
• **Decision → Implementation choice → Rationale**
• Replaced opaque modal with a small, transparent overlay.
• Added animated wavy background (CSS animation) to preserve pad visibility.
• Auto‑submit on typical PIN length (4‑6 digits) and support Enter‑key submission.
• Visual error feedback (inline color shift / shake) instead of a separate error panel.
• Kept the same API contract (`unlockPad`) – no server changes.

**Five‑named‑theme system (oxidized‑copper, walnut‑ink, storm‑slate, white, black) with light/dark variants.**
• **Decision → Mechanism → Rationale**
• Added `themeRotation.ts` mapping for time‑of‑day / location.
• Revised `useTheme.ts` to expose `setTheme` and keep persisted light/dark toggle.
• The theme picker (`ThemeToggle` upgraded to a selector) now lists the five theme names; each still has its own light/dark variant.
• Home‑page auto‑selection only when no user preference exists; manual picks persist and override auto‑rotation.
• Collected theme names in a single JavaScript enum (`ThemeName`) for reusability.

**Homepage time‑of‑day + location‑based auto‑rotation.**
• **Decision → Implementation choice → Rationale**
• Added `currentThemeBasedOnTime()` and `currentThemeBasedOnLocation()` helpers.
• If `localStorage` has no theme (`spacepad-theme`), we run the rotation helper on first mount (via `Landing.tsx` → `setTheme`).
• Location is derived from browser `Intl.DateTimeFormat().resolvedOptions().timeZone` (no geolocation prompt).
• Manual picks always win – the same behavior as existing light/dark persistence.
• Documented the trade‑off (inconsistent marketing appearance) in `DESIGN_DECISIONS.md`.

**Hidden text‑formatting control panel in editor.**
• **Decision → Reveal mechanism → Rationale**
• Panel reveals on `Ctrl+Shift+F` (keyboard shortcut) for deliberate actions.
• UI is a fixed‑position panel below the top‑bar containing: font size (small/normal/large) and colour picker.
• All selections stored in `localStorage` as `collabFormatting` (JSON) and applied via CSS custom properties on the editor container.
• No changes to the backend – frontend‑only persistence.

**Copy button → full URL.**
• **Decision → Fix → Rationale**
• Changed `CopyButton` value from `slug` to the full `window.location.origin + / + slug` in the `TopBar` component.
• No back‑end impact – copy is entirely a client‑side operation.

**Editor width with preset options.**
• **Decision → Implementation → Rationale**
• Added a `<select>` in the `TopBar` (`Width` dropdown) with **Narrow / Standard / Wide**.
• Saves the choice to `localStorage` (`spacepad-editor-width`) and sets `--canvas-max-width` accordingly.
• Presets map to pixel values: Narrow = 600 px, Standard = 740 px, Wide = 1024 px (configurable).

**Side display for uploaded media in editor.**
• **Decision → Implementation → Rationale**
• Restructured `Pad.tsx` canvas to include a flex container: `.pad-canvas` (flex) and a side panel `.pad-file-side`.
• `.pad-file-side` is a fixed‑width column that shows the existing `FileTray` component inside.
• Responsive: on screens `< 768 px` the side panel collapses to a full‑width below the editor (CSS media query).
• No new API calls – `FileTray` already handles listing/removing files.

**`/new` anonymous pad creation route.**
• **Decision → Design → Rationale**
• Added `src/pages/NewPad.tsx` which runs `createPad()` on mount and redirects to the new slug.
• Inserted the route in `src/main.tsx` as `{ path: "/new", element: <NewPad /> }`.
• Mirrors the existing homepage’s "instant creation" behavior and uses the same `createPad` endpoint.

**Formatted font‑size/persishement in `Landing.tsx`.**
• **Decision → Fallback → Rationale**
• The homepage currently uses the existing theme system. The new rotation logic only kicks in when no theme is stored – otherwise the user’s manual pick (or system preference) respects existing behavior.
• Left theme rotation for the homepage as a documented, future‑proofing choice for the design spec, but the immediate implementation is a stable light/dark toggle with manual five‑theme selector.

⚠️ **Pre‑launch blockers (unchanged from prior phases)**

**ClamAV virus scanner** – not yet wired; the backend currently logs “scanning … not possible”. The existing code fails closed, marking all uploads as `failed`.

**Redis rate limiting** – not yet wired; the limiter currently **fails open** (allows requests) if Redis is unreachable.

**Genuinely hidden formatting panel** – deliberately revealed only by a deliberate keyboard shortcut, not by hover or context menu – satisfying the “no floating formatting toolbar” anti‑pattern.

**Theme‑picker width‑selector** – placed on the top‑bar right‑side to keep UI compact.

**Side‑panel responsive collapse** – fallback to full‑width on mobile to avoid awkward side‑by‑side layouts; this satisfies the spec’s requirement for a responsive fallback where there is no natural margin space.

**File‑tray is already persistent** – the `FileTray` component is now a side panel, not a full‑page drop‑zone, matching the spec’s “side display” requirement.

**Copy‑full‑URL** – now completely client‑side, no API reliance.

All pending tasks completed with minimal back‑end impact.

### Open scope / explicit outs

* The five‑theme palette is still just CSS custom properties (no UI for customizing per‑theme colours).
* The auto‑rotation does not currently track timezone changes – could be considered a future enhancement.
* The width preset is decorative – there is no separate layout width inflection point for the editor other than this CSS variable.
* The side panel does not include file preview thumbnails (images/videos) – a future enhancement could add lazy‑loaded previews.
* The homepage still uses the plain light/dark toggle (the five‑theme selector is only on the pad/topbar).
* No alerts or toasts for any new interactions – all feedback is ambient (error styles, local‑storage indications).

**Architecture — FastAPI stays the single backend (not relitigated).** The frontend
continues to talk *only* to FastAPI's REST/WS surface. Supabase's role is narrowed to
two things: (a) the managed Postgres that SQLAlchemy connects to, and (b) the auth
provider FastAPI calls instead of its own argon2/JWT code. The alternative — frontend
calling Supabase directly, FastAPI shrunk to CRDT/files/PIN — was rejected because:
- Phases 1–4 are built and tested against FastAPI's own REST/WS surface; rewriting it
  to call Supabase directly rewrites working, tested code for no new functionality at a
  time when the priority is shipping, not architectural elegance.
- The hardest part of the system — CRDT merging via `pycrdt` — has no Supabase
  equivalent and must stay custom FastAPI code regardless; moving auth/CRUD to Supabase
  directly would not simplify the actually-hard part.
- One backend means one place enforces business rules (visibility, PIN gating,
  collaborator permissions). Splitting enforcement across Postgres RLS *and* FastAPI is a
  known source of access-control drift bugs.

**Accepted trade-offs of that choice (costs, not oversights):**
- Every request round-trips through FastAPI before reaching Supabase's Postgres — an
  extra hop versus Supabase's auto-generated REST layer, surfacing as latency if FastAPI
  and Supabase aren't co-located. If measured post-launch, the fix is colocating infra,
  not reopening this decision.
- We forgo Supabase's auto-generated CRUD API and Postgres RLS as a free safety net. All
  access control (visibility, collaborator, PIN checks) lives in FastAPI application
  code — the model already in use. RLS is intentionally **not** a second enforcement
  layer (the live tables show `rls_enabled=true` with no policies; FastAPI connects via a
  privileged pooled role that bypasses RLS, so this is a default, not a relied-upon gate).

**Database connection split.** App runtime traffic uses Supabase's *transaction-mode*
pooler (port 6543, `DATABASE_URL`); Alembic migrations use the *direct/session* endpoint
(`DATABASE_URL_DIRECT`, exposed as `Settings.migration_database_url` and consumed by
`alembic/env.py`). Transaction pooling multiplexes connections, so prepared statements
are disabled in `app/db/session.py` (asyncpg `statement_cache_size=0`, unique statement
names) — otherwise pgbouncer collides cached statements across clients. The asyncpg
driver and the existing async engine setup are unchanged: this is configuration, not a
rewrite. Migration state: the Supabase DB is at Alembic head `c3d4e5f6a7b8` (all tables
incl. `pad_pin_unlocks`); `alembic` is the single source of truth, no hand-edits.

**Auth → Supabase Auth (gotrue), with a retained legacy path for offline tests.**
`app/api/auth.py` calls Supabase Auth (`app/services/supabase_auth.py`) for
signup/login/refresh/logout/password-reset/email-verify/Google when
`supabase_auth.client` is configured, and falls back to the Phase-4 local path
(argon2 + self-minted HS256, `app/services/auth.py`) when it isn't. The branch is per
request on `supabase_auth.client is None`; the two paths are mutually exclusive and
**production runs Supabase only**. Rationale for keeping the legacy path rather than a
hard cutover: the existing 95-test suite is built entirely against the local flow with no
Supabase reachable, and this mirrors the established stub-and-flag precedent (ClamAV,
Redis, email, the `deps.py` HS256 fallback). The Supabase branch is covered by
`tests/test_supabase_auth_api.py` (a fake gotrue client).

- **Live round-trip verified (2026-06-24)** against the real project
  (`fwmbshufvlvknaencmtw`): gotrue `signup` (creates an unconfirmed `auth.users` row with
  `display_name` in user_metadata, no session — `mailer_autoconfirm=false`), `login`
  (`/token?grant_type=password` after confirming the address) and the `refresh_token`
  grant all work and return **ES256** access tokens. A token minted by the live project
  was fed through our own `app/api/deps.verify_access_token`, which verified it against the
  project **JWKS** and extracted `sub`/`email`/`aud=authenticated`/`role` — the exact path
  `get_or_sync_from_claims` consumes. The throwaway user was deleted afterward (0 left).
  Two project-config follow-ups remain launch tasks, **not** code gaps: enable
  `mailer_autoconfirm` (or wire real SMTP) so signup issues a session as the handler
  expects, and **enable the Google provider** in the dashboard (`settings.external.google`
  is currently `false`) before the Supabase Google OAuth flow can be exercised live.

- **JWT verification (checked, not assumed).** The project issues **ES256** user tokens;
  `app/api/deps.py` verifies them against the project **JWKS**
  (`/auth/v1/.well-known/jwks.json`) with audience `authenticated`. The legacy HS256
  self-minted token is accepted only outside `production` (the test harness). WS auth
  (`app/api/ws.py`) now routes the `?token=` through the same `deps.verify_access_token`,
  so the live and test paths share one verifier.
- **`public.users` ↔ `auth.users` linkage.** The existing `users` table is a public-schema
  *profile* keyed by the same UUID as `auth.users` (`public.users.id == auth.users.id`),
  populated/refreshed from token claims and gotrue responses
  (`user_service.upsert_profile` / `get_or_sync_from_claims`). No cross-schema DB foreign
  key — Supabase manages `auth.users` lifecycle independently and a cross-schema FK to a
  table we don't own is fragile; the matching-UUID invariant is enforced in application
  code instead.
- **Hand-rolled password-reset / email-verification removed from scope.** Supabase's
  native `recover` / `resend` / `verify_otp` replace them in the Supabase path; the
  reset-confirm contract `{token, new_password}` is preserved by exchanging the emailed
  `token_hash` for a session then `update_user`-ing the password server-side. The
  Phase-7 `email_tokens` flow remains wired **only** on the legacy path.
- **Google OAuth via Supabase's native provider.** Migrated from the custom direct-to-
  Google auth-code flow to Supabase's `/authorize` provider flow with server-side PKCE
  (verifier stashed in a short-lived httpOnly cookie, exchanged at the callback). One auth
  provider, not two parallel systems. The custom Google flow remains only on the legacy
  (no-Supabase) path.
- **Refresh-cookie posture preserved.** Supabase's refresh token is stored in the same
  `httpOnly`/`Secure`/`SameSite=Lax` `spacepad_refresh` cookie scoped to `/api/auth`; the
  access token goes to the SPA in the JSON body. Supabase's refresh token is never exposed
  to client-side JS.

**What deliberately did NOT change.** The CRDT/WebSocket layer and snapshot persistence
(`pycrdt`, bytea column) are untouched — they just run against Supabase-hosted Postgres.
File storage/scanning (`aioboto3` + `clamd`) is **not** moving to Supabase Storage in this
phase (a separate explicit decision if ever wanted). Redis-backed rate limiting is
untouched by the migration.

**Test tiering.** Fast unit tests stay on in-memory SQLite (`aiosqlite`) — no
Postgres-specific behavior is relied on by the existing suite, and the Supabase-hosted
schema is validated separately by Alembic being at head against the real project. A
dedicated Postgres integration tier (against Supabase or a local container) is the
launch-time follow-up if Postgres-only behavior (e.g. JWKS-verified live tokens) needs
end-to-end coverage; flagged so test/prod divergence is acknowledged, not silent.

### PIN-protected pads
- **Fourth protection mode, orthogonal to `visibility`.** A PIN-protected pad is reachable
  by anyone with the link, needs no account, but is gated behind an owner-set PIN. It sits
  between `public_edit` and `private`. PIN-protection is **mutually exclusive** with
  `visibility: private` (private is a strictly stronger gate) — rejected server-side in
  `PATCH /api/pads/{slug}` with a 422, in both directions, not merely hidden in the UI.
- **Locked pads are visible, not hidden.** `GET /api/pads/{slug}` on a locked pad returns a
  `locked: true` state with empty content (never leaks the body), so the frontend renders a
  real "enter PIN" screen rather than a 404 or sign-in wall.
- **Time-boxed unlock.** A correct PIN mints an opaque unlock token (`pad_pin_unlocks`) set
  as a path-scoped httpOnly cookie, valid for `pin_unlock_window_seconds` (default 4h, a
  `Settings` constant, not a magic number). Expiry is checked on every access; a daily
  sweep (`coldstorage.purge_expired_unlocks`, riding the existing cold-storage loop and
  cron entrypoint) reaps stale rows — housekeeping only, not required for correctness.
- **Strict brute-force protection (launch-blocking for this feature).** Unlock attempts are
  rate-limited per-pad-per-IP via the Phase-6 token bucket (`rl_pin_attempts_per_window`
  default 5 / `rl_pin_window_seconds` default 300). A wrong PIN returns 401 "Incorrect PIN";
  exceeding the limit returns a distinct 429 with `Retry-After`, so the frontend renders
  each correctly. Verification is constant-time argon2 via the shared `services/hashing.py`
  util (extracted so PIN hashing doesn't depend on the legacy auth service post-migration).
- **WS parity.** The WebSocket handshake performs the same unlock-token check (close code
  `4401`) before any CRDT state is exchanged, exactly as the visibility gate does for
  private pads.

### URL Scheme & Usernames (New)
- **Usernames added to User model:** A unique, case-insensitive `username` field (3–40 chars,
  alphanumeric + hyphens/underscores, start/end alphanumeric). Usernames are chosen at signup,
  stored normalized (lowercase), and use the same reserved-word exclusion list as pad slugs
  (e.g. `login`, `new`, `admin`, etc.) to avoid routing ambiguity. A new Alembic migration
  adds the column with a DB-level uniqueness constraint.
- **Username validation reuses slug logic:** A new `app/services/username.py` module validates
  and normalizes usernames using the same rules as custom pads slugs, inheriting the
  `RESERVED_SLUGS` list from `app/services/slug.py` to ensure usernames and pad addresses
  never collide at the top-level URL namespace.
- **Signup schema updated:** `SignupIn` now requires a `username` field (validated via the
  new username service). The schema is also updated for Supabase auth, which stores the
  username in the user's `data` metadata field.
- **Three coexisting URL formats:**
  - `/{slug}` resolves anonymous (unowned) pads unchanged.
  - `/{username}/{padname}` resolves owned pads, where padname is either the slug or a
    custom name.
  - `/new` (global), `/{username}/new`, and `/{username}/new/{custom-name}` are creation routes.
    The frontend routes handle the catch-all `/new` pattern by treating any trailing `/new`
    as a pad-creation trigger; the backend does not need special routing for this (the frontend
    navigates directly to `/new`).
- **Claiming changes a pad's address (301 redirect):** When an anonymous pad is claimed, its
  canonical address becomes `/{username}/{slug}`. The old `/{slug}` address returns a 301
  redirect to the new one, implemented in the `GET /{slug}` endpoint by detecting `owner_id`
  and redirecting if present. This ensures existing bookmarks don't break.
- **Renaming changes a pad's address with redirect tracking:** When an owned pad is renamed,
  the old custom name is appended to a new `previous_names` JSON array on the Pad model.
  The `GET /{username}/{padname}` endpoint checks if the accessed padname is in
  `previous_names` and 301-redirects to the current name if found. This aligns with the
  new requirement that renaming **changes** the address (reversing the original dashboard
  spec's "renaming doesn't change the address" behavior — a deliberate design decision change,
  see below).
- **Pad model extended:** A new `previous_names: JSON[]` column tracks old custom names for
  redirects. On rename, `update_pad_metadata` appends the old name to this list.
- **New API endpoints:**
  - `GET /api/pads/{username}/{padname}` resolves owned pads with redirect support for renames
    and detects whether a username exists (404 response detail includes `creatable: false`
    if the owner doesn't exist, so the frontend doesn't offer to create a pad under a
    non-existent user).
  - `GET /api/pads/{slug}` remains unchanged but now checks for and redirects claimed pads.
- **Design decision: renaming now changes the address.** The original dashboard spec (Phase 5)
  explicitly described renaming as a display-only change that doesn't affect the underlying
  slug/address. The new URL scheme makes a pad's custom name **its actual address**, so
  renaming necessarily changes the address. This is a deliberate pivot from the original spec,
  not an oversight. The redirect logic ensures old links continue to work, and tests verify
  the redirect behavior.


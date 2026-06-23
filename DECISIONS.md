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

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

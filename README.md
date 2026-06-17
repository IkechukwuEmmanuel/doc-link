# SpacePad

A cross-device collaborative scratchpad. Open a URL, start typing, share the link.
Edits sync live between everyone on the same pad via CRDTs — no account required.

See `DECISIONS.md` (architecture/functional) and `DESIGN_DECISIONS.md` (UI/UX) for
the rationale behind implementation choices.

## Status

| Phase | Description | State |
|-------|-------------|-------|
| 1 | Core pad CRUD + slugs (no real-time, no auth) | ✅ Done |
| 2 | Real-time collaboration (Yjs/CRDT) | ✅ Done |
| 3 | File uploads | ✅ Done |
| 4 | Authentication | ✅ Done |
| 5 | Authenticated features (incl. dashboard) | ⬜ |
| 6 | Rate limiting & abuse prevention | ⬜ |
| 7 | Polish & hardening | ⬜ |

## Stack

- **Backend**: Python 3.12, FastAPI (async), SQLAlchemy 2.x async + Alembic, PostgreSQL
- **Frontend**: React + TypeScript + Vite, CodeMirror 6
- **Real-time**: Yjs CRDT over a y-websocket-compatible server (`pycrdt` /
  `pycrdt-websocket`) hosted in-process by FastAPI
- **Storage**: S3-compatible object storage (MinIO locally) via `aioboto3`
- **Infra**: Docker Compose (Postgres, Redis, MinIO; optional ClamAV)

## How real-time works (Phase 2)

- Each pad maps to one Yjs document (a single `Text` named `content`), served over
  `WS /api/pads/{slug}/ws`. The frontend binds a CodeMirror 6 editor to that doc with
  `y-codemirror.next` + `y-websocket`.
- On first open, a room is seeded from the persisted `crdt_snapshot`; if there isn't
  one yet (e.g. a pad created before Phase 2), it falls back to the plain `content`
  column. Changes flush on a short debounce back to **both** `crdt_snapshot` and
  `content`, so the REST `GET`/`PUT`/`/raw` endpoints keep working unchanged.
- Presence (peer avatars + in-text remote cursors/selections) rides on Yjs awareness;
  the connection indicator reflects the live WebSocket status.
- Single-process, in-memory rooms are sufficient for now. Multi-node fan-out (Redis
  pub/sub or a shared Y store) is deferred to Phase 6.

## File uploads (Phase 3)

- Files are **proxied through the backend**: the browser POSTs to
  `POST /api/pads/{slug}/files`, which enforces per-pad quotas (count / per-file /
  total bytes), stores the bytes in MinIO, scans them, and persists the result.
- **Malware scanning fails closed.** A file is only ever served once its
  `scan_status` is `clean`. If the scanner is disabled or unreachable, the upload is
  marked `failed`, its bytes are deleted from storage, and downloads return 409.
  ClamAV is wired but optional — enable it with the compose `scan` profile and
  `CLAMAV_ENABLED=true`:

  ```bash
  docker compose --profile scan up -d clamav
  ```

- Downloads stream through `GET /api/pads/{slug}/files/{id}` (clean-only).

## Authentication (Phase 4)

- Email/password (argon2 hashing) **and** Google OAuth.
- **Tokens**: the refresh token is stored in a `Secure`, `httpOnly`, `SameSite=Lax`
  cookie scoped to `/api/auth`; the short-lived (15 min) access token is returned in
  the JSON body and held only in memory by the SPA. The client bootstraps its session
  on load via `POST /api/auth/refresh` and transparently refreshes once on a 401.
- A logged-in user can **claim** an anonymous pad they're viewing
  (`POST /api/pads/{slug}/claim`), which sets `owner_id` and clears `is_anonymous`.
- Visibility enforcement and pad management (dashboard) are Phase 5.

## Local development

### 1. Start infrastructure

```bash
docker compose up -d postgres redis
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example .env   # adjust if needed
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Run tests:

```bash
cd backend && source .venv/bin/activate && pytest
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 (proxies /api + the CRDT WebSocket to :8000)
```

Open the same pad URL in two browser windows to see live collaboration.

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/pads` | Create a pad (`{}` → auto slug; `{"slug","content"}` → custom) |
| GET | `/api/pads/{slug}` | Fetch a pad (404 `{creatable}` if absent) |
| PUT | `/api/pads/{slug}` | Update content (REST fallback; live path is the WebSocket) |
| GET | `/api/pads/{slug}/raw` | Raw text export (curl-friendly) |
| WS | `/api/pads/{slug}/ws` | Real-time CRDT sync (Yjs / y-websocket protocol) |
| POST | `/api/pads/{slug}/files` | Upload a file (multipart; cap-enforced, scanned) |
| GET | `/api/pads/{slug}/files` | List a pad's files + scan status |
| GET | `/api/pads/{slug}/files/{id}` | Download a file (only if `clean`) |
| DELETE | `/api/pads/{slug}/files/{id}` | Remove a file |
| POST | `/api/auth/signup` | Register (email/password); sets refresh cookie |
| POST | `/api/auth/login` | Log in; returns access token + sets refresh cookie |
| POST | `/api/auth/refresh` | Rotate refresh cookie, issue new access token |
| POST | `/api/auth/logout` | Clear the refresh cookie |
| GET | `/api/auth/me` | Current user (Bearer access token) |
| GET | `/api/auth/google/login` | Start Google OAuth |
| GET | `/api/auth/google/callback` | Google OAuth callback |
| POST | `/api/pads/{slug}/claim` | Claim an anonymous pad (auth required) |
| GET | `/health` | Health check |

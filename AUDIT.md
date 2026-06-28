# SpacePad — Production Readiness Audit

**Run date:** 2026-06-27
**Auditor:** Claude Code (automated)
**Scope:** Every implemented feature — backend test suite, lint, frontend build, live
Supabase Postgres schema, Alembic migration state, and a per-feature code/security review
of auth, pads, visibility, collaborators, PINs, files, real-time CRDT, rate limiting,
cold storage, and email.

Status legend: ✅ pass · ❌ fail · ⚠️ pass with caveats · ⬜ not run

---

## Verdict: ❌ NOT production-ready

There are **5 release blockers**. The most serious is that the application is currently
**broken against its own live database** (missing columns + un-mergeable migrations) and
has a **broken-access-control hole on all file endpoints**. The recently-added
`/{username}/{padname}` routing regressed four existing endpoints. None of these are
cosmetic — each one breaks a shipped feature or leaks data.

The underlying architecture is sound and most of the codebase is high quality (see
§"What's working well"). The blockers are concentrated in the last two commits
("save frontend progress", "update pad UI") plus the file-endpoints access gap.

---

## Summary scoreboard

| # | Area | Status | Notes |
|---|------|--------|-------|
| 1 | Backend test suite (pytest) | ❌ | 11 failed / 102 passed |
| 2 | Backend lint (ruff) | ⚠️ | 2 trivial unused-import errors |
| 3 | Frontend typecheck + build | ✅ | `tsc -b && vite build` clean |
| 4 | Alembic migration state | ❌ | **Two un-merged heads**; `upgrade head` ambiguous |
| 5 | Live DB schema vs ORM | ❌ | Live DB missing `users.username`, `pads.previous_names` |
| 6 | Auth (signup/login/refresh/OAuth) | ❌ | Breaks at runtime on live DB (see #5) |
| 7 | Pad routing (REST) | ❌ | `/{username}/{padname}` shadows raw/collaborators/files |
| 8 | Visibility & access control (pads) | ✅ | Correct in `access.py`; verified by code review |
| 9 | File endpoints access control | ❌ | **No authz** — IDOR on private/PIN pads |
| 10 | Real-time CRDT + WS auth | ✅ | PIN + write gating before room join |
| 11 | PIN-protected pads | ✅ | argon2, per-pad token, time-boxed, rate-limited |
| 12 | Rate limiting | ⚠️ | Sound, but trusts spoofable `X-Forwarded-For` |
| 13 | Cold storage flagging | ✅ | Correct; daily sweep + cron entrypoint |
| 14 | Email delivery | ❌ | Stub — logs instead of sends (legacy path) |
| 15 | Supabase RLS / advisors | ⚠️ | RLS on, no policies; app bypasses RLS via pooler |

---

## 🔴 BLOCKERS (must fix before launch)

### B1. Live DB is missing columns the code requires → auth is down in production
The ORM models declare `users.username` and `pads.previous_names` as `NOT NULL`, and the
auth/routing code reads/writes them. The **live Supabase DB does not have these columns**:

```
information_schema.columns (public.users/pads):
  users.display_name ✓   users.username ✗ (MISSING)
  pads.name ✓  pads.is_archived ✓   pads.previous_names ✗ (MISSING)
alembic_version = c3d4e5f6a7b8
```

Every authenticated request resolves the user via `get_or_sync_from_claims` →
`upsert_profile`, which emits `INSERT INTO users (... username ...)` and
`SELECT users.username ...`. Against the live DB these raise
`asyncpg UndefinedColumnError`, so **signup, login, refresh, OAuth, and every
`Depends(get_current_user)` endpoint 500 in production.** This is not covered by tests
because the test harness builds a fresh SQLite schema from the ORM (which has the columns).

### B2. Two un-merged Alembic heads → `alembic upgrade head` cannot fix B1
```
$ alembic heads
c3d4e5f6a7b8 (head)
h3i4j5k6l7m8 (head)
```
The graph branched at `f1a2b3c4d5e6` and was never merged:
- branch A: `… → c3d4e5f6a7b8` (pads.name index) ← **live DB is here**
- branch B: `… → g2h3i4j5k6l7 (add_username_to_users) → h3i4j5k6l7m8 (add_previous_names)`

The columns from B1 live on **branch B**, which was never applied. Running
`alembic upgrade head` errors ("Multiple head revisions"). **Fix:** create a merge
revision (`alembic merge -m "merge heads" c3d4e5f6a7b8 h3i4j5k6l7m8`), then
`alembic upgrade head` against the direct (session-mode) connection.

### B3. `GET /{username}/{padname}` route shadows `/{slug}/raw`, `/{slug}/collaborators`, `/{slug}/files`
`app/api/pads.py:121` registers `GET /{username}/{padname}` (two path params) **before**
the literal sub-routes. Starlette matches in declaration order, so any two-segment GET
under `/api/pads/` is captured by it:

```
GET /api/pads/raw-pad/raw  →  matched by /{username}/{padname}
                           →  {"detail":{"message":"User not found.","creatable":false}}  (404)
```

Live-reproduced. This breaks, in the running app and the SPA (which calls these slug
routes — see `frontend/src/api.ts`):
- **Raw export** `GET /{slug}/raw` → 404
- **Collaborator listing** `GET /{slug}/collaborators` → 404
- **File listing** `GET /{slug}/files` → 404

Failing tests: `test_raw_endpoint`, `test_collaborator_add_list_remove`,
`test_collaborator_endpoints_owner_only`, `test_files_api::test_list_and_delete`.
**Fix:** declare specific/literal routes before the catch-all, or namespace the
user-scoped route (e.g. `/u/{username}/{padname}`), or drop it until it's wired up
(the SPA does not currently call it).

### B4. `GET /{slug}` 301-redirects owned pads → breaks owner/collaborator access & PIN flows
`get_pad` (`app/api/pads.py:222`) now issues `301 → /api/pads/{username}/{slug}` whenever
a pad has an owner. Consequences:
- Owners/collaborators fetching their own pad receive a redirect (the test client and
  many API consumers don't auto-follow) → `assert 200` fails.
- The redirect target is itself broken/shadowed in places, and the PIN unlock cookie is
  path-scoped to `/api/pads/{slug}` (`pin.py:38`), so it is **not sent** to the
  `/{username}/...` path → PIN unlock appears to "forget" immediately.

Failing tests: `test_private_pad_allows_owner`, `test_private_editor_can_write_viewer_cannot`,
`test_public_view_blocks_stranger_write_allows_read`, and the PIN suite
(`test_owner_bypasses_pin`, `test_unlock_expires_after_window`, `test_clear_pin_reopens_pad`,
`test_pin_pad_visible_but_locked_then_unlocks` — JSONDecodeError on the empty 301 body).
**Fix:** return the pad body directly (200) instead of redirecting, or keep the canonical
URL purely client-side.

### B5. Broken access control (IDOR) on all file endpoints
`app/api/files.py` gates only on *pad existence* — there is **no** `can_read` / `can_write` /
owner / PIN check and **no authentication** on any file route:

| Route | Current check | Missing |
|-------|---------------|---------|
| `POST /{slug}/files` (upload) | pad exists | write permission |
| `GET /{slug}/files` (list) | pad exists | read permission |
| `GET /{slug}/files/{id}` (download) | pad exists + `scan_status==clean` | read permission |
| `DELETE /{slug}/files/{id}` | pad exists | owner/write permission |

So **anyone who knows a slug can download, upload to, or delete attachments on a *private*
or *PIN-protected* pad**, completely bypassing the visibility and PIN gating that the
pad-content and WebSocket layers enforce correctly. The download route especially leaks
private pad attachments to anonymous callers. (Note: the list route is currently *also*
404'd by B3, masking part of this — but upload/download/delete still work and are
unprotected.) **Fix:** thread the user through these handlers and apply
`access_service.can_read` (download/list), `can_write_content` (upload), owner/`can_write`
(delete), plus `pin_service.has_pin_access`, mirroring the REST/WS handlers.

### B6. Email delivery is a stub (legacy path)
`app/services/email.py` logs messages instead of sending them when `EMAIL_PROVIDER` is
empty (the default). The legacy (non-Supabase) password-reset and email-verify flows call
this and therefore **silently never deliver**. The Supabase path sends via gotrue, so this
is only a hard blocker if any environment runs the legacy path — but it must be resolved
(implement SMTP or confirm Supabase-only) before launch. Self-flagged in the source.

---

## 🟠 HIGH (security / correctness)

### H1. Rate limiter trusts spoofable `X-Forwarded-For`
`ratelimit.client_ip()` returns the first `X-Forwarded-For` value unconditionally. A
client can set this header to any value, getting a fresh token bucket per forged IP. This
defeats the **PIN brute-force limiter** (`check_pin_attempt`) and the pad-creation limiter.
**Fix:** derive the client IP from a trusted proxy hop count / `ProxyHeadersMiddleware`
configured for the actual deployment, not the raw header.

### H2. Supabase profile mirror ignores chosen username & can 500 on collisions
`_profile_from_gotrue` → `upsert_profile` is called **without** `username`, so it derives
one from the email local-part (`user.py:61`) instead of the username the user chose at
signup (which is sent to gotrue but never mirrored). Worse, two new users whose emails
share a local-part (`john@a.com`, `john@b.com`) collide on the unique `username`; the
`INSERT` raises `IntegrityError`, `upsert_profile` returns `None`, and
`UserOut.model_validate(None)` then **500s the signup**. **Fix:** pass the chosen username
through, and on collision generate a unique suffix instead of returning `None`.

### H3. Data protection depends entirely on the app layer
All `public` tables have RLS **enabled but with no policies** (Supabase advisor:
`rls_enabled_no_policy` ×7). That is safe *only because* the app connects through the
Postgres pooler as a role that bypasses RLS, and the anon/PostgREST API presumably isn't
used. The practical consequence: there is no defense-in-depth — the file-endpoint hole
(B5) is the whole ballgame. Decide explicitly whether PostgREST is exposed; if it ever is,
the lack of policies + the `SECURITY DEFINER` `public.rls_auto_enable()` function callable
by `anon` (advisor WARN) need attention. Also enable **leaked-password protection** in
Supabase Auth (advisor WARN).

---

## 🟡 MEDIUM

### M1. File uploads are fully buffered in memory before the size check
`files.py:upload_file` does `data = await file.read()` (entire body into RAM) and only then
enforces the per-file cap in `_enforce_caps`. A large POST exhausts memory before the 413.
**Fix:** enforce `Content-Length` / stream with an early byte-count cutoff.

### M2. Auth-tier upload caps are dead code
`file._caps()` always returns the **anonymous** caps; the `auth_max_files/bytes/total`
settings are never used even for an authenticated owner. Either wire them up (pass the user
and branch) or remove the unused config to avoid a false sense of capability.

### M3. Confirm `ENVIRONMENT=production` in prod
`cookies_secure` is `environment != "development"`, so the refresh/PIN/PKCE cookies only get
the `Secure` flag when `ENVIRONMENT` is set to something other than `development`. Verify the
prod env sets it (and `IP_HASH_SALT`, `JWT_SECRET` are rotated off the `change-me` defaults).

---

## 🟢 LOW / hygiene

- **L1.** Ruff: `app/api/pads.py:148` unused `or_` import; `app/services/pin.py:15` unused
  `uuid` import. `ruff check --fix` clears both.
- **L2.** Deprecation warnings: Starlette `HTTP_413_REQUEST_ENTITY_TOO_LARGE` /
  `HTTP_422_UNPROCESSABLE_ENTITY` constants; httpx per-request `cookies=` in tests. Non-blocking.
- **L3.** `README.md` "Status" table is stale — it lists Phases 5/6/7 as not done, but
  authenticated features, rate limiting, cold storage, PINs, and email scaffolding are all
  implemented. Update so the docs match reality.
- **L4.** Legacy direct-Google OAuth path has no `state` param (the Supabase PKCE path is
  fine). Only relevant if the legacy path is ever re-enabled.

---

## ✅ What's working well

- **WebSocket / CRDT layer** (`api/ws.py`): authorizes *before* joining the room — validates
  slug, resolves the user from `?token=`, enforces the PIN gate (distinct `4401` close code),
  then `can_write_content`; per-connection edit rate limiting via the token bucket. Solid.
- **Pad content access control** (`services/access.py`): read/write rules per visibility +
  collaborator role are correct and centralized; REST and WS share them.
- **PIN protection** (`services/pin.py`): argon2-hashed PINs, opaque per-pad unlock tokens
  scoped to the pad, time-boxed expiry checked on every access, strict per-pad-per-IP
  brute-force limiter, owner bypass. Mutually exclusive with `private` is enforced.
- **Malware scanning** (`services/scan.py` + `file.create_file`): fails **closed** — when
  the scanner is disabled/unreachable the file is `failed`, its bytes are deleted from
  storage, and downloads 409. Only `clean` files are ever served.
- **Rate limiter** (`services/ratelimit.py`): clean token-bucket model, atomic Redis Lua
  for cross-process correctness, deliberate fail-open with salted-hashed IP keys.
- **Supabase auth wrapper** (`services/supabase_auth.py`, `api/deps.py`): ES256 JWT
  verification against project JWKS with audience check; OAuth via PKCE (S256); password
  recovery avoids an account-existence oracle.
- **Email/reset tokens** (`models/token.py`): only a SHA-256 hash is stored; single-use and
  time-boxed.
- **Frontend**: `tsc -b && vite build` is clean; no hardcoded hosts (all `/api` relative,
  proxied in dev).
- **Test coverage**: 102 passing tests across auth, visibility, PINs, files, CRDT, rate
  limiting, cold storage, and slug validation. The 11 failures are all explained by B3/B4
  above, not by gaps in the assertions.

---

## Reproduction notes

```bash
# Backend
cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest -q                       # 11 failed, 102 passed
ruff check .                    # 2 errors
alembic heads                   # shows TWO heads  ← B2

# Frontend
cd frontend && npm install && npm run build   # clean ✅

# Live schema (via Supabase MCP)
select version_num from alembic_version;       # c3d4e5f6a7b8
# users.username / pads.previous_names absent   ← B1
```

### Failing tests → blocker mapping
| Test | Blocker |
|------|---------|
| `test_pads_api::test_raw_endpoint` | B3 |
| `test_files_api::test_list_and_delete` | B3 |
| `test_pad_management_api::test_collaborator_add_list_remove` | B3 |
| `test_pad_management_api::test_collaborator_endpoints_owner_only` | B3 |
| `test_visibility_api::test_private_pad_allows_owner` | B4 |
| `test_visibility_api::test_private_editor_can_write_viewer_cannot` | B4 |
| `test_visibility_api::test_public_view_blocks_stranger_write_allows_read` | B4 |
| `test_pin_api::test_pin_pad_visible_but_locked_then_unlocks` | B4 |
| `test_pin_api::test_owner_bypasses_pin` | B4 |
| `test_pin_api::test_unlock_expires_after_window` | B4 |
| `test_pin_api::test_clear_pin_reopens_pad` | B4 |

---

## Suggested fix order

1. **B2 → B1**: merge the Alembic heads, apply to live DB, confirm `users.username` /
   `pads.previous_names` exist. (Unblocks all auth.)
2. **B5**: add authz to the file endpoints. (Closes the data-leak.)
3. **B3 + B4**: fix pad route ordering and drop the owned-pad redirect. (Restores raw,
   collaborators, file listing, owner access, PIN flows — and turns the test suite green.)
4. **B6 / H1 / H2**: email provider, trusted client-IP, username mirroring.
5. Mediums, then hygiene. Re-run `pytest` (expect 113/113) and re-check Supabase advisors.

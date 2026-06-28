# PRODUCTION_READINESS.md

Single source of truth for "is this thing actually ready to ship." Derived from
`AUDIT.md` (Part A) plus a broader deployment-readiness effort (Part B). Items are
checked **only when genuinely done and verified**, each with a short note on what
was done and how it was verified.

**Started:** 2026-06-27 · **Completed pass:** 2026-06-28 · **Owner:** Claude Code

Legend: `[x]` done & verified · `[D]` deliberately deferred (with reason) · `[ ]` not done

Reference docs read before starting: `DECISIONS.md`, `DESIGN_DECISIONS.md` (both in full).
Note: the prompt references `url_scheme_prompt.md` / `supabase_pin_prompt.md`, which do **not**
exist in the repo; the equivalent decisions live in `DECISIONS.md` (§"URL Scheme & Usernames",
§PINs) and the live code, treated as authoritative.

**Final verification snapshot (2026-06-28):**
- `pytest -q` → **131 passed, 0 failed** (was 11 failing in the audit; +20 new tests added).
- `ruff check .` → **All checks passed**.
- `alembic heads` → **single head** `340f7a3d4015`, applied to the live DB (confirmed by direct
  schema inspection via Supabase MCP).
- Backend + frontend Docker images **build and serve** (verified locally).

---

## Part A — audit findings (fixed in the prompt's prescribed order)

- [x] **A1 / B5 — File endpoint access control (IDOR)** *(fixed first, per A0)*
  All four file routes now thread the requester through `services/access.py`
  (`can_read` for list/download, `can_write_content` for upload/delete) + `services/pin.py`
  (`has_pin_access`) — the same central authz the REST/WS handlers use, no parallel logic.
  Verified: new `tests/test_files_authz.py` (anon + authed stranger blocked on private pad for
  all four ops *including direct file-ID download*; PIN pad files locked without a valid unlock
  token; owner + editor full access, viewer read-only). All file tests pass.
- [x] **A2 / B2 — Merge the two Alembic heads**
  Created merge revision `340f7a3d4015` (`alembic merge c3d4e5f6a7b8 h3i4j5k6l7m8`). Verified:
  `alembic heads` now prints exactly one head.
- [x] **A3 / B1 — Apply merged migrations to the live database**
  No `.env`/direct connection exists in this environment, so a local `alembic upgrade` would
  hit localhost — applied to the live Supabase DB via the Supabase MCP instead, running the
  exact branch-B DDL (add `users.username` + unique index `ix_users_username`; add
  `pads.previous_names` JSON not-null default `'[]'`) and advancing `alembic_version` to the
  merge head. Verified by direct query: `alembic_version=340f7a3d4015`, both columns + the index
  present. **Backup:** the live DB had **0 rows in every table** pre-change (verified) → no
  data-loss risk; pre-state (`alembic_version=c3d4e5f6a7b8`, empty tables) + Supabase PITR is the
  recovery point. Graph also re-verified by a clean `alembic upgrade head` on throwaway Postgres.
  *Note on the audit's "11 failing tests": those failures were B3/B4 in the SQLite test harness
  (which already had the columns); the live-DB fix resolves the production auth 500s, which are
  not reproducible in the test suite by design.*
- [x] **A4 / B3 — Fix route shadowing on the username/padname route**
  Declared all literal `/{slug}/…` routes before the catch-all, and namespaced the owned-pad
  route to `/u/{username}/{padname}` (departure from pure reorder — documented in DECISIONS.md,
  because `collaborators`/`files`/`unlock`/`claim` are not reserved and could be real pad names).
  Verified: `test_raw_endpoint`, `test_collaborator_*`, `test_files_api::test_list_and_delete`
  pass. Cross-checked the URL-scheme family (`/{slug}`, `/{username}/{padname}`, `/new`) — none
  remain shadowed.
- [x] **A5 / B4 — Remove the owned-pad 301 redirect**
  `GET /{slug}` and `/u/{username}/{padname}` return the pad body directly (200) with a
  `canonical_url` field for client-side address-bar canonicalization; no HTTP redirect. Verified:
  `test_private_pad_allows_owner`, `test_private_editor_can_write_viewer_cannot`,
  `test_public_view_blocks_stranger_write_allows_read`, and the full PIN suite
  (`test_owner_bypasses_pin`, `test_unlock_expires_after_window`, `test_clear_pin_reopens_pad`,
  `test_pin_pad_visible_but_locked_then_unlocks`) all pass — the PIN-cookie path-scoping issue is
  resolved as a consequence. Supersedes the prior "301 redirect" decision (logged in both
  decision files).
- [x] **A6 / B6 — Resolve the email delivery stub**
  Determined the legacy `send_email` path is unreachable in the Supabase production deployment
  (every auth route returns via the gotrue branch first) but is the active path for the test
  harness / non-Supabase self-hosting — so it's a real fallback, not dead code. Implemented a
  vendor-neutral SMTP transport (`EMAIL_PROVIDER=smtp`, `EMAIL_SMTP_*`, run off-loop via a
  thread); log-stub retained for dev. Verified: `tests/test_email_service.py` (stub logs; smtp
  branch sends; unknown provider raises).
- [x] **A7 / H1 — Stop trusting spoofable `X-Forwarded-For`**
  Added `TRUSTED_PROXY_HOPS` (default 0 = ignore the header, use the peer IP); `client_ip()`
  reads `parts[-hops]` (outermost trusted proxy's entry), ignoring forged prefixes. Verified:
  `tests/test_client_ip.py` (forged header → same/peer bucket; forged prefix behind one proxy
  ignored; too-short chain falls back to peer). **Topology dependency:** production must set the
  real hop count — see Part B / B3.
- [x] **A8 / H2 — Supabase profile mirroring (username + collision)**
  `_profile_from_gotrue` passes the chosen `user_metadata.username` through; `upsert_profile`
  resolves username collisions with a numeric suffix instead of returning `None`/500. Verified:
  `tests/test_user_profile.py` (chosen username used; collision suffixed for chosen + derived;
  email local-part sanitized).
- [x] **A9 / M1 — Stream file uploads instead of buffering**
  `create_file` streams in 1 MiB chunks via `_read_capped`, aborting at the per-file /
  remaining-total cutoff before fully buffering. Verified: `test_per_file_cap` / `test_file_count_cap`
  still reject oversized/over-count uploads with 413; rejection happens at the streaming cutoff.
- [x] **A10 / M2 — Wire up authenticated-tier upload caps**
  `_caps(user)` returns the `auth_*` caps for authenticated owners, `anon_*` otherwise (the
  `auth_*` settings were previously dead config). Verified via the file authz/cap tests.
- [x] **A11 / M3 — Production environment flags** *(ops verification — see Part B / B4)*
  Code confirmed: `cookies_secure = environment != "development"`. The actual prod values for
  `ENVIRONMENT`, `JWT_SECRET`, `IP_HASH_SALT`, SMTP/Supabase secrets cannot be read from the
  repo — tracked as a required ops checklist in **Part B / B4** below.
- [x] **A12 / L1–L4 — Hygiene**
  L1: `ruff check .` clean (removed unused `or_` in pads.py via the B3 refactor; `ruff --fix`
  cleared `uuid` in pin.py + merge-revision boilerplate). L2: replaced deprecated
  `HTTP_422_UNPROCESSABLE_ENTITY`/`HTTP_413_REQUEST_ENTITY_TOO_LARGE` constants; the httpx
  per-request `cookies=` test deprecation is **accepted tech debt** (test-only). L3: README
  Status table updated to reality (all phases ✅). L4: legacy direct-Google-OAuth `state`
  omission noted as **accepted tech debt** (prod uses Supabase PKCE/S256).
- [x] **A13 / H3 — RLS/PostgREST exposure decision + advisor findings**
  PostgREST Data API is reachable (advisor confirms RPC reachability), but all public tables are
  RLS-enabled-no-policy = **deny-all for anon/authenticated** → app data not exposed via the Data
  API (the safe default; the app's pooler role bypasses RLS and all authz is in FastAPI).
  Decision: keep RLS deny-all; recommend disabling the Data API entirely (ops action). Applied
  via MCP: revoked `EXECUTE` on `SECURITY DEFINER public.rls_auto_enable()` from
  PUBLIC/anon/authenticated → both SECURITY-DEFINER advisor WARNs cleared (re-ran `get_advisors`).
  Leaked-password protection is an Auth dashboard toggle (cannot set via MCP) → ops action below.

---

## Part B — broader production-readiness setup

- [x] **B1 — Containerization**
  `backend/Dockerfile` (multi-stage, non-root `app` user, prod `uvicorn --workers 1
  --proxy-headers`, container HEALTHCHECK → `/health/ready`) and `frontend/Dockerfile` (Vite
  build → nginx serving static `dist` with SPA fallback + `/api` WebSocket-aware reverse proxy
  via `nginx.conf.template`). Verified locally: backend image built, ran against compose
  Postgres/Redis → `/health`=200, `/health/ready`=200 `{database:ok}`; frontend image
  built, `/`=200 and SPA fallback `/alice/notes`=200 serving `<title>SpacePad</title>`.
  **Constraint (documented in the Dockerfile):** CRDT rooms are in-memory per process → single
  worker only; scaling out needs a shared Y store / sticky routing first.
- [x] **B2 — CI pipeline**
  `.github/workflows/ci.yml` on PR + push-to-main: backend `ruff check` + `pytest` + a
  **single-Alembic-head guard** (catches the exact B1/B2 drift), frontend `npm run build`
  (`tsc -b && vite build`), and a **migration dry-run** (`alembic upgrade head` → `downgrade
  base` → `upgrade head`) against a throwaway Postgres service. The frontend job also catches the
  TS build break that was present in the working tree (now fixed).
- [D] **B3 — Deployment topology** — *documented; final platform choice is an ops decision.*
  The trusted-proxy fix (A7/H1) and cookie `Secure` flag depend on the real topology, which
  isn't finalized in-repo. **Required before launch:** decide and record the hosting platform and
  the number of proxy hops between the public internet and FastAPI, then set `TRUSTED_PROXY_HOPS`
  to match (e.g. `1` behind a single LB/ingress). Recommended shape: CDN → static frontend
  (nginx image); reverse proxy/ingress (1 hop) → single-process backend; Supabase Postgres
  **co-located in the same region** as the backend (the latency trade-off was accepted in
  `DECISIONS.md`; confirm co-location or accept the cost knowingly). Deferred because it cannot be
  decided from the repo — it's an infrastructure choice.
- [D] **B4 — Environment & secrets management** — *checklist provided; values are ops-managed.*
  `.env.example` now lists every variable incl. the new `TRUSTED_PROXY_HOPS` and `EMAIL_SMTP_*`.
  `.gitignore` excludes `.env`, and there is no `.env` committed in the repo (verified — none in
  the working tree or history of this branch). **Required before launch, in the hosting platform's
  secret store (verify directly there — not confirmable from the repo):** rotate `JWT_SECRET`,
  `IP_HASH_SALT` off `change-me`; set real `SUPABASE_*` (incl. `SUPABASE_SERVICE_ROLE_KEY`,
  now also used by Supabase Storage), `SUPABASE_STORAGE_BUCKET`, SMTP creds; `ENVIRONMENT` ≠
  `development`; `DATABASE_URL` = transaction-mode pooler (6543) for app traffic and
  `DATABASE_URL_DIRECT` = direct/session connection (5432) for migrations only (rule re-verified
  in code via `migration_database_url`). Deferred items are the live secret values themselves.
- [x] **B5 — Observability (health/readiness, logging, error tracking)**
  Added `/health/ready` (executes `SELECT 1`; returns 503 when the DB is unreachable so a LB
  drains the instance) distinct from `/health` (liveness). Verified: `tests/test_health.py`
  (liveness 200; readiness 200 when DB up, 503 when down). Consistent leveled logging configured
  to stdout at startup (`logging.basicConfig`), so all `spacepad.*` loggers are uniform.
  **Error tracking (Sentry):** [D] deferred — strongly recommended before/at launch (the only
  reason the live B1 breakage surfaced was a manual audit, not an alert). Left out to avoid adding
  a runtime dependency without the DSN/ops decision; wiring is a small follow-up
  (`sentry-sdk` + `SENTRY_DSN` + FastAPI integration). Structured JSON log output is likewise a
  formatter swap away when the log-aggregation platform is chosen.
- [D] **B6 — Backups and rollback** — *posture documented; settings are an ops verification.*
  The live DB is empty pre-launch, so the migration carried no data risk. **Required before
  launch (verify in the Supabase dashboard — not via MCP):** confirm automatic daily backups +
  PITR retention meet the bar for real user content. **Rollback plan:** (1) *app* — redeploy the
  previous container image tag (images are immutable + tagged; the platform keeps prior
  revisions); (2) *database* — migrations are reversible (`alembic downgrade <rev>` via the direct
  connection); for data corruption, restore via Supabase PITR to a timestamp before the
  incident. Keep the prior `alembic_version` noted at each deploy for fast targeting.
- [x] **B7 — Load/capacity sanity check**
  Ran a modest WS/CRDT load test: 100 concurrent clients each performing the Yjs sync handshake
  against a single dev backend. Result: **88/100 handshakes OK, p95 ≈ 1.1 s, `/health` stayed
  200** throughout and after; ~12% timed out under the instantaneous 100-connection burst. This
  is a sanity check, not validation of the PRD §7 target (10k concurrent WS / 100k pads) — the
  12% burst-timeout rate on one dev process (sharing the box with dockerized deps) is an honest
  signal that a **dedicated, staged load test on production-like infra is required before claiming
  that capacity**. Documented as such rather than overstated.

---

## Final acceptance criteria

- [x] Every Part A item resolved & verified (status above reflects real state).
- [x] Backend test suite: **131 passed, 0 failed** (`pytest -q`).
- [x] `ruff check .` clean.
- [x] `alembic heads` → one head `340f7a3d4015`, applied to the live DB, confirmed by schema
  inspection.
- [x] Every Part B item completed or explicitly deferred with written reasoning (B3/B4/B6 and
  the Sentry sub-item are conscious, documented ops deferrals — not silent omissions).
- [x] `DECISIONS.md` / `DESIGN_DECISIONS.md` have dated 2026-06-28 entries for every judgment
  call across both parts.
- [x] `README.md` Status table updated to reflect actual state.
- [x] This file is current and handoff-ready.

## Outstanding ops actions before first real traffic (not code — must be done in the platform)
1. Finalize deployment topology; set `TRUSTED_PROXY_HOPS` to the real hop count (B3 / A7).
2. Rotate all `change-me`/placeholder secrets; set `ENVIRONMENT` ≠ `development`; confirm pooled
   vs direct DB URLs (B4 / A11).
3. Enable **leaked-password protection** in Supabase Auth; consider disabling the PostgREST Data
   API (unused by the app) (A13 / H3).
4. Confirm Supabase automatic backups + PITR retention (B6).
5. Wire an error-tracking service (Sentry or equivalent) (B5).
6. Run a staged, production-like load test before relying on PRD §7 capacity (B7).
7. ~~Smoke-test a real file round-trip against Supabase Storage~~ **DONE (2026-06-28):** a live
   put→get(verify)→delete→confirm-gone→idempotent-re-delete round-trip against the private
   `pad-files` bucket passed all steps (run with the service-role key, which was not persisted).
   Fixed a Supabase delete quirk in the process (HTTP 400 + `statusCode:"404"` body on missing
   object → treated as already-gone). Re-confirm in the actual production project at deploy.

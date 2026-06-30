import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import BrandWordmark from "../components/BrandWordmark";
import ThemeToggle from "../components/ThemeToggle";
import {
  PadListItem,
  Redirect,
  Visibility,
  claimPad,
  createPad,
  killRedirect,
  listMyPads,
  listRedirects,
  patchPad,
} from "../api";
import { useAuth } from "../auth";
import { fullTimestamp, formatBytes, relativeTime } from "../format";
import { useTheme } from "../useTheme";

const VISIBILITY: Record<Visibility, { glyph: string; label: string }> = {
  public_edit: { glyph: "🌐", label: "Anyone can edit" },
  public_view: { glyph: "👁", label: "Anyone can view" },
  private: { glyph: "🔒", label: "Private" },
};

/** Extract the pad's address segment (slug or name) from a pasted URL/path. */
function parseSlug(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  let path = trimmed;
  try {
    path = new URL(trimmed).pathname;
  } catch {
    // not a full URL — treat as a path or bare slug
  }
  const parts = path.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
}

export default function AccountPads() {
  const { user, ready, authedFetch, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();

  const [pads, setPads] = useState<PadListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [archived, setArchived] = useState(false);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  // Claim-a-pad form
  const [claimUrl, setClaimUrl] = useState("");
  const [claimTokenInput, setClaimTokenInput] = useState("");
  const [claimPin, setClaimPin] = useState("");
  const [claimMsg, setClaimMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [claiming, setClaiming] = useState(false);

  // Inline rename + "old links" per card
  const [renamingSlug, setRenamingSlug] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [linksSlug, setLinksSlug] = useState<string | null>(null);
  const [links, setLinks] = useState<Redirect[]>([]);

  // Redirect to login once the session has settled and there's no user.
  useEffect(() => {
    if (ready && !user) {
      const next = encodeURIComponent("/account/pads");
      navigate(`/login?next=${next}`, { replace: true });
    }
  }, [ready, user, navigate]);

  // ~150ms debounce on the search input (dashboard spec §2).
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQuery(query), 150);
    return () => clearTimeout(id);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPads(await listMyPads(authedFetch, { archived, q: debouncedQuery }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [authedFetch, archived, debouncedQuery]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function newPad() {
    try {
      const pad = await createPad(undefined, authedFetch);
      navigate(`/${pad.slug}`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  // Optimistic local patch so inline edits feel immediate.
  function applyLocal(slug: string, patch: Partial<PadListItem>) {
    setPads((prev) =>
      prev
        .map((p) => (p.slug === slug ? { ...p, ...patch } : p))
        // archive/unarchive drops the row from the current view
        .filter((p) => p.is_archived === archived)
    );
  }


  async function setArchivedFlag(slug: string, value: boolean) {
    applyLocal(slug, { is_archived: value });
    try {
      await patchPad(authedFetch, slug, { is_archived: value });
    } catch (e) {
      setError((e as Error).message);
      load();
    }
  }

  async function submitClaim(e: React.FormEvent) {
    e.preventDefault();
    setClaimMsg(null);
    const slug = parseSlug(claimUrl);
    if (!slug) {
      setClaimMsg({ ok: false, text: "Enter the pad's URL." });
      return;
    }
    setClaiming(true);
    const res = await claimPad(
      authedFetch,
      slug,
      claimTokenInput.trim(),
      claimPin.trim() || undefined
    );
    setClaiming(false);
    if (res.kind === "ok") {
      setClaimMsg({ ok: true, text: `Claimed “${res.pad.name || res.pad.slug}”.` });
      setClaimUrl("");
      setClaimTokenInput("");
      setClaimPin("");
      load();
    } else {
      setClaimMsg({ ok: false, text: res.message });
    }
  }

  async function commitRename(slug: string) {
    const next = renameValue.trim().toLowerCase();
    setRenamingSlug(null);
    if (!next) return;
    try {
      const updated = await patchPad(authedFetch, slug, { name: next });
      applyLocal(slug, { name: updated.name });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function toggleLinks(slug: string) {
    if (linksSlug === slug) {
      setLinksSlug(null);
      return;
    }
    setLinksSlug(slug);
    try {
      setLinks(await listRedirects(authedFetch, slug));
    } catch {
      setLinks([]);
    }
  }

  async function removeLink(slug: string, id: string) {
    try {
      await killRedirect(authedFetch, slug, id);
      setLinks((prev) => prev.filter((r) => r.id !== id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!ready) return <div className="pad-state" />;
  if (!user) return null;

  return (
    <main className="dash">
      <header className="dash-header">
        <div className="dash-header-left">
          <Link to="/" className="brand-mark" aria-label="River home">
            <BrandWordmark />
          </Link>
          <h1 className="dash-title">My Pads</h1>
        </div>
        <div className="dash-header-right">
          <input
            type="search"
            className="dash-search"
            placeholder="Search pads…"
            aria-label="Search pads by name or slug"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="button" className="btn btn-primary" onClick={newPad}>
            New Pad
          </button>
          <ThemeToggle theme={theme} onToggle={toggle} />
          {user && (
            <span className="topbar-user">
              <span className="topbar-user-name" title={user.email}>
                {user.display_name || user.email}
              </span>
              <button type="button" className="text-link" onClick={logout}>
                Log out
              </button>
            </span>
          )}
        </div>
      </header>

      <div className="dash-toolbar">
        <div className="dash-tabs" role="tablist" aria-label="Pad views">
          <button
            type="button"
            role="tab"
            aria-selected={!archived}
            className={`dash-tab ${!archived ? "is-active" : ""}`}
            onClick={() => setArchived(false)}
          >
            Active
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={archived}
            className={`dash-tab ${archived ? "is-active" : ""}`}
            onClick={() => setArchived(true)}
          >
            Archived
          </button>
        </div>
      </div>

      <form className="dash-claim" onSubmit={submitClaim}>
        <div className="dash-claim-fields">
          <label className="dash-claim-field">
            <span>Claim a pad — its URL</span>
            <input
              type="text"
              className="dash-claim-input"
              placeholder="myriver.app/crisp-badger-68"
              value={claimUrl}
              onChange={(e) => setClaimUrl(e.target.value)}
            />
          </label>
          <label className="dash-claim-field">
            <span>Claim token</span>
            <input
              type="text"
              className="dash-claim-input"
              placeholder="token from the pad"
              value={claimTokenInput}
              onChange={(e) => setClaimTokenInput(e.target.value)}
            />
          </label>
          <label className="dash-claim-field">
            <span>PIN (if locked)</span>
            <input
              type="text"
              className="dash-claim-input"
              inputMode="text"
              placeholder="optional"
              value={claimPin}
              onChange={(e) => setClaimPin(e.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={claiming}>
            {claiming ? "Claiming…" : "Claim"}
          </button>
        </div>
        {claimMsg && (
          <p
            className={claimMsg.ok ? "dash-claim-ok" : "error"}
            role={claimMsg.ok ? "status" : "alert"}
          >
            {claimMsg.text}
          </p>
        )}
      </form>

      {error && (
        <p className="error dash-error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <div className="dash-empty" aria-busy="true" />
      ) : pads.length === 0 ? (
        <div className="dash-empty">
          {debouncedQuery ? (
            <p>No pads match “{debouncedQuery}”.</p>
          ) : archived ? (
            <p>No archived pads.</p>
          ) : (
            <>
              <p>You don’t have any pads yet.</p>
              <button type="button" className="btn btn-primary" onClick={newPad}>
                Create your first pad
              </button>
            </>
          )}
        </div>
      ) : (
        <div className="dash-grid" role="list">
          {pads.map((pad) => (
            <article key={pad.id} className="dash-card" role="listitem">
              <div
                className="dash-card-accent"
                style={{
                  // subtle decorative accent: pick a muted presence color by index
                  // (reusing peer presence palette is out of scope here; choose fixed muted tints)
                  background: `linear-gradient(90deg, rgba(107,98,88,0.14), rgba(107,98,88,0.06))`,
                }}
                aria-hidden
              />
              <div className="dash-card-body">
                {renamingSlug === pad.slug ? (
                  <input
                    className="dash-rename-input"
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value.toLowerCase())}
                    onBlur={() => commitRename(pad.slug)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitRename(pad.slug);
                      if (e.key === "Escape") setRenamingSlug(null);
                    }}
                    aria-label="New pad name"
                    placeholder="new-name"
                  />
                ) : (
                  <Link to={`/${user.username}/${pad.name || pad.slug}`} className="dash-card-name-link">
                    {pad.name ? (
                      <div className="dash-name">{pad.name}</div>
                    ) : (
                      <div className="dash-name dash-name--slug">{pad.slug}</div>
                    )}
                    {pad.name && <div className="dash-name-slug">/{pad.slug}</div>}
                  </Link>
                )}

                <div className="dash-card-meta">
                  <div className="dash-card-time" title={fullTimestamp(pad.updated_at)}>
                    {relativeTime(pad.updated_at)}
                  </div>
                  <div className="dash-card-meta" aria-hidden>
                    <span className="dash-card-meta">{VISIBILITY[pad.visibility].glyph}</span>
                  </div>
                </div>


                <div className="dash-card-foot">
                  <div className="dash-actions" style={{ opacity: 1 }}>
                    <button
                      type="button"
                      className="dash-action"
                      onClick={() => {
                        const url = `${window.location.origin}/${user.username}/${pad.name || pad.slug}`;
                        const doFallback = (text: string) => {
                          try {
                            const ta = document.createElement("textarea");
                            ta.value = text;
                            ta.setAttribute("readonly", "");
                            ta.style.position = "absolute";
                            ta.style.left = "-9999px";
                            document.body.appendChild(ta);
                            const sel = document.getSelection();
                            const range = document.createRange();
                            range.selectNodeContents(ta);
                            sel?.removeAllRanges();
                            sel?.addRange(range);
                            const ok = document.execCommand("copy");
                            sel?.removeAllRanges();
                            document.body.removeChild(ta);
                            return ok;
                          } catch {
                            return false;
                          }
                        };
                        if (navigator.clipboard && navigator.clipboard.writeText) {
                          navigator.clipboard.writeText(url).catch(() => doFallback(url));
                        } else {
                          doFallback(url);
                        }
                      }}
                      aria-label={`Copy link to ${pad.slug}`}
                    >
                      Copy link
                    </button>
                    <button
                      type="button"
                      className="dash-action"
                      onClick={() => navigate(`/${user.username}/${pad.name || pad.slug}`)}
                    >
                      Open
                    </button>
                    <button
                      type="button"
                      className="dash-action"
                      onClick={() => {
                        setRenameValue(pad.name || "");
                        setRenamingSlug(pad.slug);
                      }}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      className="dash-action"
                      onClick={() => toggleLinks(pad.slug)}
                      aria-expanded={linksSlug === pad.slug}
                    >
                      Old links
                    </button>
                    <button
                      type="button"
                      className="dash-action"
                      onClick={() => setArchivedFlag(pad.slug, !archived)}
                    >
                      {archived ? 'Unarchive' : 'Archive'}
                    </button>
                  </div>
                  <div className="dash-card-meta">
                    <div className="dash-cell-size">{formatBytes(pad.size_bytes)}</div>
                  </div>
                </div>

                {linksSlug === pad.slug && (
                  <div className="dash-links">
                    {links.length === 0 ? (
                      <p className="dash-links-empty">No old links for this pad.</p>
                    ) : (
                      <ul className="dash-links-list">
                        {links.map((r) => (
                          <li key={r.id} className="dash-links-row">
                            <code className="dash-links-name">{r.old_slug}</code>
                            <button
                              type="button"
                              className="dash-action dash-action--danger"
                              onClick={() => removeLink(pad.slug, r.id)}
                              aria-label={`Remove old link ${r.old_slug}`}
                            >
                              Kill
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}

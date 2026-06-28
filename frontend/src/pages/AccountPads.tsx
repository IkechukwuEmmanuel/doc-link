import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import BrandWordmark from "../components/BrandWordmark";
import ThemeToggle from "../components/ThemeToggle";
import {
  PadListItem,
  PinFormat,
  Visibility,
  createPad,
  deletePad,
  listMyPads,
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
const VISIBILITY_ORDER: Visibility[] = ["public_edit", "public_view", "private"];

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

  // Redirect to login once the session has settled and there's no user.
  useEffect(() => {
    if (ready && !user) navigate("/login", { replace: true });
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

  async function rename(slug: string, name: string) {
    const trimmed = name.trim();
    applyLocal(slug, { name: trimmed || null });
    try {
      await patchPad(authedFetch, slug, { name: trimmed || null });
    } catch (e) {
      setError((e as Error).message);
      load();
    }
  }

  async function changeVisibility(slug: string, visibility: Visibility) {
    try {
      await patchPad(authedFetch, slug, { visibility });
      applyLocal(slug, { visibility });
    } catch (e) {
      setError((e as Error).message); // e.g. "Verify your email…" for private
    }
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

  async function remove(slug: string) {
    setPads((prev) => prev.filter((p) => p.slug !== slug));
    try {
      await deletePad(authedFetch, slug);
    } catch (e) {
      setError((e as Error).message);
      load();
    }
  }

  // PIN protection is orthogonal to visibility (mutually exclusive only with
  // `private`, enforced server-side and by disabling the control in the UI).
  async function setPin(slug: string, pin: string, format: PinFormat) {
    try {
      await patchPad(authedFetch, slug, {
        pin_protected: true,
        pin,
        pin_format: format,
      });
      applyLocal(slug, { pin_protected: true });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function clearPin(slug: string) {
    applyLocal(slug, { pin_protected: false });
    try {
      await patchPad(authedFetch, slug, { pin_protected: false });
    } catch (e) {
      setError((e as Error).message);
      load();
    }
  }

  if (!ready || (!user && !ready)) return <div className="pad-state" />;

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
        <table className="dash-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Last edited</th>
              <th scope="col">Visibility</th>
              <th scope="col" className="dash-col-size">
                Size
              </th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {pads.map((pad) => (
              <PadRow
                key={pad.id}
                pad={pad}
                archived={archived}
                onRename={rename}
                onChangeVisibility={changeVisibility}
                onSetPin={setPin}
                onClearPin={clearPin}
                onArchive={(value) => setArchivedFlag(pad.slug, value)}
                onDelete={() => remove(pad.slug)}
              />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

interface RowProps {
  pad: PadListItem;
  archived: boolean;
  onRename: (slug: string, name: string) => void;
  onChangeVisibility: (slug: string, v: Visibility) => void;
  onSetPin: (slug: string, pin: string, format: PinFormat) => void;
  onClearPin: (slug: string) => void;
  onArchive: (value: boolean) => void;
  onDelete: () => void;
}

function PadRow({
  pad,
  archived,
  onRename,
  onChangeVisibility,
  onSetPin,
  onClearPin,
  onArchive,
  onDelete,
}: RowProps) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(pad.name ?? "");
  const [visOpen, setVisOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pinEditing, setPinEditing] = useState(false);
  const [pinDraft, setPinDraft] = useState("");
  const [pinFormat, setPinFormat] = useState<PinFormat>("numeric");
  const renameRef = useRef<HTMLInputElement>(null);

  const isPrivate = pad.visibility === "private";

  function commitPin() {
    if (!pinDraft) return;
    onSetPin(pad.slug, pinDraft, pinFormat);
    setPinDraft("");
    setPinEditing(false);
  }

  useEffect(() => {
    if (renaming) renameRef.current?.focus();
  }, [renaming]);

  function commitRename() {
    setRenaming(false);
    if (draft !== (pad.name ?? "")) onRename(pad.slug, draft);
  }

  async function copyLink() {
    const url = `${window.location.origin}/${pad.slug}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked — non-fatal */
    }
  }

  const vis = VISIBILITY[pad.visibility];
  // Display rule (dashboard spec §2): show the custom name when set, otherwise
  // the slug in mono. Never-renamed pads read as their slug.
  const displayName = pad.name?.trim();

  return (
    <tr className="dash-row">
      <td className="dash-cell-name">
        {renaming ? (
          <input
            ref={renameRef}
            className="dash-rename-input"
            value={draft}
            aria-label={`Rename ${pad.slug}`}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setDraft(pad.name ?? "");
                setRenaming(false);
              }
            }}
          />
        ) : (
          <Link to={`/${pad.slug}`} className="dash-name-link">
            {displayName ? (
              <span className="dash-name">{displayName}</span>
            ) : (
              <span className="dash-name dash-name--slug">{pad.slug}</span>
            )}
            {displayName && <span className="dash-name-slug">/{pad.slug}</span>}
          </Link>
        )}
      </td>

      <td className="dash-cell-time" title={fullTimestamp(pad.updated_at)}>
        {relativeTime(pad.updated_at)}
      </td>

      <td className="dash-cell-vis">
        <div className="dash-vis">
          <button
            type="button"
            className="dash-vis-trigger"
            aria-haspopup="menu"
            aria-expanded={visOpen}
            aria-label={`Visibility: ${vis.label}. Change`}
            onClick={() => setVisOpen((o) => !o)}
          >
            <span aria-hidden="true">{vis.glyph}</span>
            <span className="dash-vis-label">{vis.label}</span>
          </button>
          {visOpen && (
            <ul className="dash-vis-menu" role="menu">
              {VISIBILITY_ORDER.map((v) => (
                <li key={v} role="none">
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={pad.visibility === v}
                    className="dash-vis-option"
                    onClick={() => {
                      setVisOpen(false);
                      if (v !== pad.visibility) onChangeVisibility(pad.slug, v);
                    }}
                  >
                    <span aria-hidden="true">{VISIBILITY[v].glyph}</span>
                    {VISIBILITY[v].label}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* PIN protection — orthogonal to visibility, hidden for private pads
              (a private pad already requires an account, a stronger gate). */}
          {!isPrivate && (
            <div className="dash-pin">
              {pad.pin_protected ? (
                <span className="dash-pin-on">
                  <span aria-hidden="true">🔢</span> PIN on
                  <button
                    type="button"
                    className="dash-pin-link"
                    onClick={() => onClearPin(pad.slug)}
                  >
                    Remove
                  </button>
                </span>
              ) : pinEditing ? (
                <span className="dash-pin-edit" role="group" aria-label="Set a PIN">
                  <select
                    className="dash-pin-format"
                    aria-label="PIN format"
                    value={pinFormat}
                    onChange={(e) => setPinFormat(e.target.value as PinFormat)}
                  >
                    <option value="numeric">Numbers</option>
                    <option value="alphanumeric">Letters &amp; numbers</option>
                  </select>
                  <input
                    className="dash-pin-input"
                    type="text"
                    inputMode={pinFormat === "numeric" ? "numeric" : "text"}
                    autoComplete="off"
                    placeholder="PIN"
                    aria-label={`PIN for ${pad.slug}`}
                    value={pinDraft}
                    autoFocus
                    onChange={(e) => setPinDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitPin();
                      if (e.key === "Escape") {
                        setPinDraft("");
                        setPinEditing(false);
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="dash-pin-link"
                    onClick={commitPin}
                    disabled={!pinDraft}
                  >
                    Set
                  </button>
                  <button
                    type="button"
                    className="dash-pin-link"
                    onClick={() => {
                      setPinDraft("");
                      setPinEditing(false);
                    }}
                  >
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="dash-pin-link"
                  onClick={() => setPinEditing(true)}
                >
                  Add PIN
                </button>
              )}
            </div>
          )}
        </div>
      </td>

      <td className="dash-cell-size">{formatBytes(pad.size_bytes)}</td>

      <td className="dash-cell-actions">
        {confirmingDelete ? (
          <span className="dash-confirm" role="group" aria-label="Confirm delete">
            <span className="dash-confirm-label">Delete?</span>
            <button
              type="button"
              className="dash-action dash-action--danger"
              onClick={onDelete}
            >
              Yes
            </button>
            <button
              type="button"
              className="dash-action"
              onClick={() => setConfirmingDelete(false)}
            >
              No
            </button>
          </span>
        ) : (
          // Always in the DOM (keyboard/touch reachable); revealed on
          // row hover / focus-within via CSS (dashboard spec §2).
          <span className="dash-actions">
            <button
              type="button"
              className="dash-action"
              onClick={copyLink}
              aria-label={`Copy link to ${pad.slug}`}
            >
              {copied ? "Copied" : "Copy link"}
            </button>
            <button
              type="button"
              className="dash-action"
              onClick={() => {
                setDraft(pad.name ?? "");
                setRenaming(true);
              }}
            >
              Rename
            </button>
            <button
              type="button"
              className="dash-action"
              onClick={() => onArchive(!archived)}
            >
              {archived ? "Unarchive" : "Archive"}
            </button>
            <button
              type="button"
              className="dash-action dash-action--danger"
              onClick={() => setConfirmingDelete(true)}
            >
              Delete
            </button>
          </span>
        )}
      </td>
    </tr>
  );
}

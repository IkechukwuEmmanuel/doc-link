import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import TopBar from "../components/TopBar";
import ThemeToggle from "../components/ThemeToggle";
import CollabEditor from "../components/CollabEditor";
import FileTray from "../components/FileTray";
import { ConnectionState } from "../components/ConnectionIndicator";
import { PresencePeer } from "../components/PresenceStack";
import { Pad as PadModel, PinFormat, createPad, getPad, unlockPad } from "../api";
import { useAuth } from "../auth";
import { useTheme } from "../useTheme";

type Status = "loading" | "missing" | "invalid" | "ready" | "error" | "forbidden";

export default function Pad() {
  const { slug = "" } = useParams();
  const location = useLocation();
  const seed = (location.state as { seed?: string } | null)?.seed ?? "";
  const { theme, toggle } = useTheme();
  const { user, authedFetch } = useAuth();

  const [status, setStatus] = useState<Status>("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const [pad, setPad] = useState<PadModel | null>(null);
  const [peers, setPeers] = useState<PresencePeer[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connected");
  const [ownerId, setOwnerId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    getPad(slug, authedFetch)
      .then((res) => {
        if (cancelled) return;
        if (res.kind === "found") {
          setPad(res.pad);
          setOwnerId(res.pad.owner_id);
          setStatus("ready");
        } else if (res.kind === "forbidden") {
          setStatus("forbidden");
        } else {
          setStatus(res.creatable ? "missing" : "invalid");
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setErrorMsg((e as Error).message);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, authedFetch]);

  async function claim() {
    const resp = await authedFetch(`/api/pads/${encodeURIComponent(slug)}/claim`, {
      method: "POST",
    });
    if (resp.ok) {
      const claimed = await resp.json();
      setOwnerId(claimed.owner_id);
    }
  }

  async function createHere() {
    try {
      await createPad(slug, authedFetch);
      const res = await getPad(slug, authedFetch);
      if (res.kind === "found") {
        setPad(res.pad);
        setOwnerId(res.pad.owner_id);
      }
      setStatus("ready");
    } catch (e) {
      setErrorMsg((e as Error).message);
      setStatus("error");
    }
  }

  if (status === "loading") return <div className="pad-state" />; // no spinner

  if (status === "invalid")
    return (
      <div className="pad-state">
        <p>“{slug}” isn’t a valid pad name.</p>
        <Link className="text-link" to="/">
          Go home
        </Link>
      </div>
    );

  if (status === "forbidden")
    return (
      <div className="pad-state">
        <p>This pad is private.</p>
        <p className="dash-confirm-label">
          Ask the owner to share it with you{user ? "" : ", or sign in"}.
        </p>
        <Link className="text-link" to={user ? "/account/pads" : "/login"}>
          {user ? "Go to your pads" : "Sign in"}
        </Link>
      </div>
    );

  if (status === "error")
    return (
      <div className="pad-state">
        <p className="error">{errorMsg || "Something went wrong."}</p>
        <Link className="text-link" to="/">
          Go home
        </Link>
      </div>
    );

  if (status === "missing")
    return (
      <div className="pad-state">
        <p>This pad doesn’t exist yet — create it?</p>
        <div className="pad-state-actions">
          <button className="btn btn-primary" onClick={createHere}>
            Create /{slug}
          </button>
          <Link className="text-link" to="/">
            Cancel
          </Link>
        </div>
      </div>
    );

  // PIN-gated and not yet unlocked: show the locked screen (the pad's existence
  // is never hidden — only its content is gated). Unlocking swaps in the real pad.
  if (pad?.locked)
    return (
      <LockedPad
        slug={slug}
        pinFormat={pad.pin_format}
        onUnlocked={(unlocked) => {
          setPad(unlocked);
          setOwnerId(unlocked.owner_id);
        }}
      />
    );

  const canEdit = pad?.can_edit ?? true;

  return (
    <div className="pad">
      <TopBar
        slug={slug}
        peers={peers}
        connection={canEdit ? connection : "noaccess"}
        theme={theme}
        onToggleTheme={toggle}
        canClaim={!!user && ownerId === null}
        onClaim={claim}
      />
      <div className="pad-canvas-scroll">
        <div className="pad-canvas">
          {canEdit ? (
            <CollabEditor
              slug={slug}
              seed={seed}
              onPeersChange={setPeers}
              onConnectionChange={setConnection}
            />
          ) : (
            <div className="editor editor--readonly" aria-readonly="true">
              {pad?.content || ""}
            </div>
          )}
          <FileTray slug={slug} />
        </div>
      </div>
    </div>
  );
}

interface LockedPadProps {
  slug: string;
  pinFormat: PinFormat | null;
  onUnlocked: (pad: PadModel) => void;
}

/** Calm, on-brand locked screen (not a modal). A correct PIN unlocks the pad for
 *  the session window; an incorrect PIN and a rate-limited lockout render as
 *  distinct inline messages, consistent with the auth pages' error style. */
function LockedPad({ slug, pinFormat, onUnlocked }: LockedPadProps) {
  const { theme, toggle } = useTheme();
  const { authedFetch } = useAuth();
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [lockedOut, setLockedOut] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const numeric = pinFormat === "numeric";

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!pin || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await unlockPad(slug, pin, authedFetch);
      if (result.kind === "ok") {
        onUnlocked(result.pad);
        return;
      }
      if (result.kind === "rate_limited") {
        setLockedOut(true);
        const mins = result.retryAfter ? Math.ceil(result.retryAfter / 60) : 0;
        setError(
          mins
            ? `Too many attempts. Try again in about ${mins} minute${mins === 1 ? "" : "s"}.`
            : result.message
        );
      } else {
        setError(result.message);
      }
      setPin("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="landing-corner">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>

      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-title">This pad is locked</h1>
        <p className="pad-locked-hint">
          Enter the {numeric ? "PIN" : "passcode"} to view <code>/{slug}</code>.
        </p>

        <label className="auth-field">
          <span>{numeric ? "PIN" : "Passcode"}</span>
          <input
            ref={inputRef}
            type="password"
            inputMode={numeric ? "numeric" : "text"}
            pattern={numeric ? "[0-9]*" : undefined}
            autoComplete="off"
            value={pin}
            disabled={lockedOut}
            onChange={(e) => setPin(e.target.value)}
          />
        </label>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button
          className="btn btn-primary"
          type="submit"
          disabled={submitting || lockedOut || !pin}
        >
          {submitting ? "…" : "Unlock"}
        </button>

        <Link className="text-link auth-home" to="/">
          ← Back home
        </Link>
      </form>
    </main>
  );
}

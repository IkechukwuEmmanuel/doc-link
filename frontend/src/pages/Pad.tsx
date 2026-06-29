import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import TopBar from "../components/TopBar";
import ThemeToggle from "../components/ThemeToggle";
import CollabEditor from "../components/CollabEditor";
import FileTray from "../components/FileTray";
import { ConnectionState } from "../components/ConnectionIndicator";
import { PresencePeer } from "../components/PresenceStack";
import {
  Pad as PadModel,
  PinFormat,
  createPad,
  generateClaimToken,
  getPad,
  unlockPad,
} from "../api";
import { useAuth } from "../auth";
import { useTheme } from "../useTheme";

type Status = "loading" | "missing" | "invalid" | "ready" | "error" | "forbidden";

export default function Pad() {
  const { padname, slug = "" } = useParams();
  const location = useLocation();
  const seed = (location.state as { seed?: string } | null)?.seed ?? "";
  const { theme, toggle } = useTheme();
  const { user, authedFetch } = useAuth();

  // Determine the pad identifier: if username/padname exist, use padname; otherwise use slug
  const padIdentifier = padname || slug;

  const [status, setStatus] = useState<Status>("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const [pad, setPad] = useState<PadModel | null>(null);
  const [peers, setPeers] = useState<PresencePeer[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connected");
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [claimToken, setClaimToken] = useState<string | null>(null);
  const [claimErr, setClaimErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    getPad(padIdentifier, authedFetch)
      .then((res) => {
        if (cancelled) return;
        if (res.kind === "found") {
          setPad(res.pad);
          setOwnerId(res.pad.owner_id);
          // Canonicalize the address bar client-side (AUDIT B4 — no HTTP 301):
          // an old/slug URL stays resolvable but the bar shows the canonical one.
          if (
            res.pad.canonical_url &&
            res.pad.canonical_url !== window.location.pathname
          ) {
            window.history.replaceState(null, "", res.pad.canonical_url);
          }
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
  }, [padIdentifier, authedFetch]);

  // Claiming happens from the dashboard (spec §3). In-pad we only mint a
  // time-bound claim token for the user to submit there.
  async function claim() {
    setClaimErr("");
    try {
      const { token } = await generateClaimToken(padIdentifier, authedFetch);
      setClaimToken(token);
    } catch (e) {
      setClaimErr((e as Error).message);
    }
  }

  async function createHere() {
    try {
      await createPad(padIdentifier, authedFetch);
      const res = await getPad(padIdentifier, authedFetch);
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
        <p>"{padIdentifier}" isn't a valid pad name.</p>
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
        <p>This pad doesn't exist yet — create it?</p>
        <div className="pad-state-actions">
          <button className="btn btn-primary" onClick={createHere}>
            Create /{padIdentifier}
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
        slug={padIdentifier}
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
        slug={padIdentifier}
        peers={peers}
        connection={canEdit ? connection : "noaccess"}
        theme={theme}
        onToggleTheme={toggle}
        canClaim={!!user && ownerId === null}
        onClaim={claim}
      />
      {claimErr && (
        <div className="claim-banner" role="alert">
          <span className="error">{claimErr}</span>
        </div>
      )}
      {claimToken && (
        <div className="claim-banner" role="status">
          <p className="claim-banner-title">Claim token generated</p>
          <p className="claim-banner-hint">
            Paste this pad's URL and the token below into{" "}
            <Link to="/account/pads" className="text-link">
              your dashboard → “Claim a pad”
            </Link>
            . It expires in a few minutes.
          </p>
          <code className="claim-banner-token">{claimToken}</code>
          <div className="claim-banner-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => navigator.clipboard?.writeText(claimToken).catch(() => {})}
            >
              Copy token
            </button>
            <button
              type="button"
              className="text-link"
              onClick={() => setClaimToken(null)}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
      <div className="pad-canvas-scroll">
        <div className="pad-layout">
          <div className="pad-canvas">
            {canEdit ? (
              <CollabEditor
                slug={padIdentifier}
                seed={seed}
                onPeersChange={setPeers}
                onConnectionChange={setConnection}
              />
            ) : (
              <div className="editor editor--readonly" aria-readonly="true">
                {pad?.content || ""}
              </div>
            )}
          </div>
          <aside className="pad-file-side">
            <FileTray slug={padIdentifier} />
          </aside>
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

/** Calm, on-brand locked screen (not a modal). A correct PIN unlocks the pad for the session window; an incorrect PIN and a rate-limited lockout render as distinct inline messages, consistent with the auth pages' error style. */
function LockedPad({ slug, pinFormat, onUnlocked }: LockedPadProps) {
  const { theme, toggle } = useTheme();
  const { authedFetch } = useAuth();
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [lockedOut, setLockedOut] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [visualError, setVisualError] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const numeric = pinFormat === "numeric";

  // Auto-submit logic for numeric PINs
  useEffect(() => {
    if (!submitting && !lockedOut) {
      if (numeric && pin.length >= 4 && pin.length <= 6) {
        submitPin();
      }
    }
  }, [pin, submitting, lockedOut, numeric]);

  // Handle Enter key press
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter" && !submitting && !lockedOut) {
        e.preventDefault();
        submitPin();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  async function submitPin() {
    if (!pin || submitting) return;
    setSubmitting(true);
    setVisualError(false);
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
        setVisualError(true);
        return;
      }
      setError(result.message);
      setVisualError(true);
      setTimeout(() => {
        setVisualError(false);
      }, 3000);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="locked-pad-overlay" role="alertdialog" aria-label="Pad Unlock Required">
      <div className="wavy-background">
        <svg className="wavy-lines" viewBox="0 0 100 100" preserveAspectRatio="none">
          <path className="wave-1" d="M0 30 Q25 20 50 30 T100 30 L100 100 L0 100 Z" />
          <path className="wave-2" d="M0 50 Q25 40 50 50 T100 50 L100 100 L0 100 Z" />
          <path className="wave-3" d="M0 70 Q25 60 50 70 T100 70 L100 100 L0 100 Z" />
        </svg>
      </div>

      <div className="content-container">
        <div className="landing-corner">
          <ThemeToggle theme={theme} onToggle={toggle} />
        </div>

        <h2 className="locked-pad-title">This pad is locked</h2>
        <p className="locked-pad-hint">
          Enter the {numeric ? "PIN" : "passcode"} to view <code>/{slug}</code>.
        </p>

        <label className="locked-input-label">
          <span>{numeric ? "PIN" : "Passcode"}</span>
          <input
            ref={inputRef}
            type="password"
            inputMode={numeric ? "numeric" : "text"}
            pattern={numeric ? "[0-9]*" : "[a-zA-Z0-9]*"}
            autoComplete="off"
            value={pin}
            disabled={lockedOut || submitting}
            onChange={(e) => setPin(e.target.value)}
            className={`locked-input ${visualError ? "has-error" : ""}`}
            placeholder={numeric ? "1234" : "enter passcode"}
            aria-label={numeric ? "PIN" : "Passcode"}
          />
        </label>

        {error && (
          <p className="locked-input-error" role="alert" aria-live="polite">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
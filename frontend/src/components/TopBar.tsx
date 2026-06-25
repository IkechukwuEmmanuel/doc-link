import { useState } from "react";
import { Link } from "react-router-dom";

import ConnectionIndicator, { ConnectionState } from "./ConnectionIndicator";
import CopyButton from "./CopyButton";
import PresenceStack, { PresencePeer } from "./PresenceStack";
import ThemeToggle from "./ThemeToggle";
import { useAuth } from "../auth";

interface Props {
  slug: string;
  peers: PresencePeer[];
  connection: ConnectionState;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  canClaim?: boolean;
  onClaim?: () => void;
}

const dismissKey = (slug: string) => `spacepad-hint-dismissed:${slug}`;

type WidthPreset = "narrow" | "standard" | "wide";
const WIDTH_KEY = "spacepad-editor-width";

function getWidthValue(preset: WidthPreset): number {
  switch (preset) {
    case "narrow":
      return 600;
    case "wide":
      return 1024;
    default:
      return 740;
  }
}

export default function TopBar({
  slug,
  peers,
  connection,
  theme,
  onToggleTheme,
  canClaim,
  onClaim,
}: Props) {
  const { user, logout } = useAuth();
  const [hintDismissed, setHintDismissed] = useState(
    () => localStorage.getItem(dismissKey(slug)) === "1"
  );
  const [widthPreset, setWidthPreset] = useState<WidthPreset>(() => {
    const stored = localStorage.getItem(WIDTH_KEY);
    return (stored as WidthPreset) || "standard";
  });
  const fullUrl = `${window.location.origin}/${slug}`;

  function dismissHint() {
    localStorage.setItem(dismissKey(slug), "1");
    setHintDismissed(true);
  }

  function changeWidth(preset: WidthPreset) {
    setWidthPreset(preset);
    localStorage.setItem(WIDTH_KEY, preset);
    document.documentElement.style.setProperty(
      "--canvas-max-width",
      `${getWidthValue(preset)}px`
    );
  }

  useState(() => {
    const stored = localStorage.getItem(WIDTH_KEY);
    if (stored) {
      document.documentElement.style.setProperty(
        "--canvas-max-width",
        `${getWidthValue(stored as WidthPreset)}px`
      );
    }
  });

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link to="/" className="brand-mark" aria-label="SpacePad home">
          ✦
        </Link>
        <CopyButton value={fullUrl} label={slug} ariaLabel={`Copy pad URL ${slug}`} />
      </div>

      <div className="topbar-right">
        <PresenceStack peers={peers} />
        <ConnectionIndicator state={connection} />
        {user && canClaim && (
          <button type="button" className="claim-btn" onClick={onClaim}>
            Claim this pad
          </button>
        )}
        {!user && !hintDismissed && (
          <span className="signin-hint">
            <Link to="/login">Sign in to keep this pad forever</Link>
            <button
              type="button"
              className="hint-dismiss"
              onClick={dismissHint}
              aria-label="Dismiss"
            >
              ✕
            </button>
          </span>
        )}
        {user && (
          <span className="topbar-user">
            <Link to="/account/pads" className="text-link">
              My Pads
            </Link>
            <span className="topbar-user-name" title={user.email}>
              {user.display_name || user.email}
            </span>
            <button type="button" className="text-link" onClick={logout}>
              Log out
            </button>
          </span>
        )}
        <div className="width-selector">
          <label htmlFor="width-select" className="text-xs">
            Width
          </label>
          <select
            id="width-select"
            value={widthPreset}
            onChange={(e) => changeWidth(e.target.value as WidthPreset)}
            className="width-select"
          >
            <option value="narrow">Narrow</option>
            <option value="standard">Standard</option>
            <option value="wide">Wide</option>
          </select>
        </div>
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
    </header>
  );
}

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

  function dismissHint() {
    localStorage.setItem(dismissKey(slug), "1");
    setHintDismissed(true);
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link to="/" className="brand-mark" aria-label="SpacePad home">
          ✦
        </Link>
        <CopyButton value={slug} label={slug} ariaLabel={`Copy pad URL ${slug}`} />
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
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
    </header>
  );
}

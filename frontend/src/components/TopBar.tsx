import { useState } from "react";
import { Link } from "react-router-dom";

import ConnectionIndicator, { ConnectionState } from "./ConnectionIndicator";
import CopyButton from "./CopyButton";
import PresenceStack, { PresencePeer } from "./PresenceStack";
import ThemeToggle from "./ThemeToggle";

interface Props {
  slug: string;
  peers: PresencePeer[];
  connection: ConnectionState;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

const dismissKey = (slug: string) => `spacepad-hint-dismissed:${slug}`;

export default function TopBar({ slug, peers, connection, theme, onToggleTheme }: Props) {
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
        {!hintDismissed && (
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
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
    </header>
  );
}

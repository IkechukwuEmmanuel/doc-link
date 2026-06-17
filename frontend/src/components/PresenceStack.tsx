import { PresenceColor } from "../styles/presence";

export interface PresencePeer {
  id: string;
  label: string; // e.g. "Anonymous Otter"
  color: PresenceColor;
  initial: string;
}

const MAX_VISIBLE = 4;

/** Presence avatar stack (design spec 2.2). Fixed height; overflow collapses to
    a +N circle rather than wrapping. Live peers are wired in Phase 2. */
export default function PresenceStack({ peers }: { peers: PresencePeer[] }) {
  if (peers.length === 0) return null;

  const visible = peers.slice(0, MAX_VISIBLE);
  const overflow = peers.length - visible.length;

  return (
    <div className="presence-stack" role="group" aria-label={`${peers.length} people here`}>
      {visible.map((p) => (
        <span
          key={p.id}
          className="presence-avatar"
          style={{ backgroundColor: p.color.solid }}
          title={p.label}
          aria-label={p.label}
        >
          {p.initial}
        </span>
      ))}
      {overflow > 0 && (
        <span className="presence-avatar presence-overflow" title={`${overflow} more`}>
          +{overflow}
        </span>
      )}
    </div>
  );
}

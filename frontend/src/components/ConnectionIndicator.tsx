export type ConnectionState = "connected" | "reconnecting" | "reconnected";

interface Props {
  state: ConnectionState;
}

/** Far-right connection indicator (design spec 2.2). Silence = healthy:
    renders nothing visible when connected, but always reserves its slot so
    appearing/disappearing causes no layout shift. Real WS wiring lands in Phase 2. */
export default function ConnectionIndicator({ state }: Props) {
  return (
    <div className="conn-indicator" aria-live="polite">
      {state === "reconnecting" && <span className="conn conn-reconnecting">Reconnecting…</span>}
      {state === "reconnected" && <span className="conn conn-reconnected">Reconnected</span>}
    </div>
  );
}

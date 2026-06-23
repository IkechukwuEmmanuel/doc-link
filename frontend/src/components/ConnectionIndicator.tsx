export type ConnectionState =
  | "connected"
  | "reconnecting"
  | "reconnected"
  | "noaccess";

interface Props {
  state: ConnectionState;
}

/** Far-right connection indicator (design spec 2.2). Silence = healthy:
    renders nothing visible when connected, but always reserves its slot so
    appearing/disappearing causes no layout shift.

    "noaccess" is deliberately distinct from "reconnecting": a permission
    rejection (WS close 4403) is not a network drop, and must not masquerade as
    one — the user is told their access changed, not that we're retrying. */
export default function ConnectionIndicator({ state }: Props) {
  return (
    <div className="conn-indicator" aria-live="polite">
      {state === "reconnecting" && (
        <span className="conn conn-reconnecting">Reconnecting…</span>
      )}
      {state === "reconnected" && (
        <span className="conn conn-reconnected">Reconnected</span>
      )}
      {state === "noaccess" && (
        <span className="conn conn-noaccess">View-only — no edit access</span>
      )}
    </div>
  );
}

import { useEffect, useRef } from "react";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, placeholder } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";
import { yCollab } from "y-codemirror.next";

import { PresencePeer } from "./PresenceStack";
import { presenceColorForIndex } from "../styles/presence";
import { ConnectionState } from "./ConnectionIndicator";
import { editorTheme } from "./collabTheme";
import { useAuth } from "../auth";

// WS close codes the backend uses to reject a handshake (see app/api/ws.py).
const CLOSE_NO_ACCESS = 4403;
const CLOSE_RATE_LIMITED = 4429;

interface Props {
  slug: string;
  seed: string;
  onPeersChange: (peers: PresencePeer[]) => void;
  onConnectionChange: (state: ConnectionState) => void;
}

interface AwarenessUser {
  name: string;
  colorIndex: number;
}

const ANIMALS = [
  "Otter", "Fox", "Heron", "Lynx", "Wren", "Ibex",
  "Moth", "Crane", "Vole", "Newt", "Finch", "Marten",
];

function localUser(): AwarenessUser {
  // Stable per browser session so reloads keep the same identity/color.
  const KEY = "spacepad-identity";
  const stored = sessionStorage.getItem(KEY);
  if (stored) return JSON.parse(stored) as AwarenessUser;
  const colorIndex = Math.floor(Math.random() * 10);
  const name = `Anonymous ${ANIMALS[Math.floor(Math.random() * ANIMALS.length)]}`;
  const user = { name, colorIndex };
  sessionStorage.setItem(KEY, JSON.stringify(user));
  return user;
}

export default function CollabEditor({
  slug,
  seed,
  onPeersChange,
  onConnectionChange,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const { getAccessToken } = useAuth();

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const ydoc = new Y.Doc();
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/api/pads/${encodeURIComponent(slug)}`;
    // The access token rides as a query param — a browser WS handshake can't set
    // an Authorization header (matches the backend's documented choice).
    const token = getAccessToken();
    const provider = new WebsocketProvider(url, "ws", ydoc, {
      params: token ? { token } : {},
    });
    const ytext = ydoc.getText("content");

    const me = localUser();
    const myColor = presenceColorForIndex(me.colorIndex);
    provider.awareness.setLocalStateField("user", {
      name: me.name,
      color: myColor.solid,
      colorLight: myColor.selection,
      colorIndex: me.colorIndex,
    });

    // Seed text from the homepage transition once, when the doc is empty and
    // we're the first client to sync.
    let seeded = false;
    const trySeed = () => {
      if (seeded || !seed) return;
      if (provider.synced && ytext.length === 0) {
        ytext.insert(0, seed);
        seeded = true;
      }
    };
    provider.on("sync", trySeed);

    const updatePeers = () => {
      const peers: PresencePeer[] = [];
      provider.awareness.getStates().forEach((state, clientId) => {
        if (clientId === provider.awareness.clientID) return;
        const user = state.user as
          | { name: string; colorIndex: number }
          | undefined;
        if (!user) return;
        peers.push({
          id: String(clientId),
          label: user.name,
          color: presenceColorForIndex(user.colorIndex ?? 0),
          initial: user.name.replace(/^Anonymous /, "").charAt(0).toUpperCase(),
        });
      });
      onPeersChange(peers);
    };
    provider.awareness.on("change", updatePeers);

    let hasConnected = false;
    let rejected = false;
    const onStatus = ({ status }: { status: string }) => {
      if (rejected) return;
      if (status === "connected") {
        onConnectionChange(hasConnected ? "reconnected" : "connected");
        hasConnected = true;
      } else if (status === "disconnected" && hasConnected) {
        onConnectionChange("reconnecting");
      }
    };
    provider.on("status", onStatus);

    // A permission rejection (4403) is not a network drop — stop reconnecting
    // and surface a distinct "no access" state instead of "reconnecting…".
    const onClose = (event: CloseEvent | null) => {
      if (
        event &&
        (event.code === CLOSE_NO_ACCESS || event.code === CLOSE_RATE_LIMITED)
      ) {
        rejected = true;
        provider.shouldConnect = false;
        provider.disconnect();
        onConnectionChange("noaccess");
      }
    };
    provider.on("connection-close", onClose);

    const view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: ytext.toString(),
        extensions: [
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          placeholder("Start typing…"),
          EditorView.lineWrapping,
          editorTheme,
          yCollab(ytext, provider.awareness),
        ],
      }),
    });
    view.focus();

    return () => {
      provider.off("sync", trySeed);
      provider.off("status", onStatus);
      provider.off("connection-close", onClose);
      provider.awareness.off("change", updatePeers);
      view.destroy();
      provider.destroy();
      ydoc.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  return <div ref={hostRef} className="editor cm-host" />;
}

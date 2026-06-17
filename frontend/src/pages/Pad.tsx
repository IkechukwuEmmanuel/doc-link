import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import TopBar from "../components/TopBar";
import CollabEditor from "../components/CollabEditor";
import FileTray from "../components/FileTray";
import { ConnectionState } from "../components/ConnectionIndicator";
import { PresencePeer } from "../components/PresenceStack";
import { createPad, getPad } from "../api";
import { useTheme } from "../useTheme";

type Status = "loading" | "missing" | "invalid" | "ready" | "error";

export default function Pad() {
  const { slug = "" } = useParams();
  const location = useLocation();
  const seed = (location.state as { seed?: string } | null)?.seed ?? "";
  const { theme, toggle } = useTheme();

  const [status, setStatus] = useState<Status>("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const [peers, setPeers] = useState<PresencePeer[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connected");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    getPad(slug)
      .then((res) => {
        if (cancelled) return;
        if (res.kind === "found") {
          setStatus("ready");
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
  }, [slug]);

  async function createHere() {
    try {
      await createPad(slug);
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

  return (
    <div className="pad">
      <TopBar
        slug={slug}
        peers={peers}
        connection={connection}
        theme={theme}
        onToggleTheme={toggle}
      />
      <div className="pad-canvas-scroll">
        <div className="pad-canvas">
          <CollabEditor
            slug={slug}
            seed={seed}
            onPeersChange={setPeers}
            onConnectionChange={setConnection}
          />
          <FileTray slug={slug} />
        </div>
      </div>
    </div>
  );
}

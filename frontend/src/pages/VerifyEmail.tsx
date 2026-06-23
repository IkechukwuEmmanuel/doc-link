import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { confirmEmailVerification } from "../api";
import { useAuth } from "../auth";

type State = "verifying" | "done" | "error" | "notoken";

export default function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { reloadUser } = useAuth();
  const [state, setState] = useState<State>(token ? "verifying" : "notoken");
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true; // guard React StrictMode double-invoke
    confirmEmailVerification(token)
      .then(() => {
        setState("done");
        reloadUser().catch(() => {});
      })
      .catch(() => setState("error"));
  }, [token, reloadUser]);

  return (
    <main className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Email verification</h1>
        {state === "verifying" && <p className="auth-switch">Verifying…</p>}
        {state === "done" && (
          <p className="auth-switch">
            Your email is verified. You can now make pads private.
          </p>
        )}
        {state === "notoken" && (
          <p className="error" role="alert">
            This link is missing its token.
          </p>
        )}
        {state === "error" && (
          <p className="error" role="alert">
            This verification link is invalid or has expired.
          </p>
        )}
        <p className="auth-home">
          <Link className="text-link" to="/">
            Go home
          </Link>
        </p>
      </div>
    </main>
  );
}

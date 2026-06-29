import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { confirmPasswordReset } from "../api";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await confirmPasswordReset(token, password);
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Choose a new password</h1>
        {!token ? (
          <p className="error" role="alert">
            This link is missing its token. Request a new reset email.
          </p>
        ) : done ? (
          <p className="auth-switch">
            Your password has been reset.{" "}
            <Link className="text-link" to="/">
              Go to your pads
            </Link>
          </p>
        ) : (
          <form className="auth-form" onSubmit={submit}>
            <label className="auth-field">
              New password
              <input
                type="password"
                autoComplete="new-password"
                minLength={8}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="btn btn-primary" disabled={busy}>
              Reset password
            </button>
          </form>
        )}
        <p className="auth-home">
          <Link className="text-link" to="/login">
            Back to log in
          </Link>
        </p>
      </div>
    </main>
  );
}

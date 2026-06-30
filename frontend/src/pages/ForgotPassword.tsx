import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { requestPasswordReset } from "../api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    // Always resolves the same way — we never reveal whether the account exists.
    await requestPasswordReset(email);
    setBusy(false);
    setSent(true);
  }

  return (
    <main className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Reset your password</h1>
        {sent ? (
          <p className="auth-switch">
            If an account exists for <strong>{email}</strong>, we’ve sent a reset
            link. It expires in 1 hour.
          </p>
        ) : (
          <form className="auth-form" onSubmit={submit}>
            <label className="auth-field">
              Email
              <input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              Send reset link
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

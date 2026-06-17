import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ThemeToggle from "../components/ThemeToggle";
import { useAuth } from "../auth";
import { useTheme } from "../useTheme";

interface Props {
  mode: "login" | "signup";
}

export default function AuthPage({ mode }: Props) {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const { login, signup } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (isSignup) {
        await signup(email, password, displayName || undefined);
      } else {
        await login(email, password);
      }
      navigate("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="landing-corner">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>

      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-title">{isSignup ? "Create account" : "Sign in"}</h1>

        {isSignup && (
          <label className="auth-field">
            <span>Display name (optional)</span>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={80}
              autoComplete="nickname"
            />
          </label>
        )}

        <label className="auth-field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            autoFocus
          />
        </label>

        <label className="auth-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={isSignup ? 8 : 1}
            autoComplete={isSignup ? "new-password" : "current-password"}
          />
        </label>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "…" : isSignup ? "Create account" : "Sign in"}
        </button>

        <a className="btn btn-secondary auth-google" href="/api/auth/google/login">
          Continue with Google
        </a>

        <p className="auth-switch">
          {isSignup ? (
            <>
              Already have an account? <Link to="/login">Sign in</Link>
            </>
          ) : (
            <>
              New here? <Link to="/signup">Create an account</Link>
            </>
          )}
        </p>

        <Link className="text-link auth-home" to="/">
          ← Back home
        </Link>
      </form>
    </main>
  );
}

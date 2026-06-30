import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ThemeToggle from "../components/ThemeToggle";
import { useAuth } from "../auth";
import { useTheme } from "../useTheme";

interface Props {
  mode: "login" | "signup";
}

// Mirrors the server rules in app/services/username.py + slug.py RESERVED_SLUGS,
// so the user gets inline feedback instead of a 422 after submitting.
const RESERVED_USERNAMES = new Set([
  "login", "signup", "api", "account", "admin", "static",
  "assets", "raw", "new", "health", "about",
]);
// 3–40 chars, lowercase alphanumeric + hyphens/underscores, start/end
// alphanumeric, no consecutive hyphens.
const USERNAME_RE = /^[a-z0-9](?:[a-z0-9_]|-(?!-)){1,38}[a-z0-9]$/;

/** Returns an error message for an invalid username, or null if it's valid. */
function validateUsername(raw: string): string | null {
  const u = raw.trim().toLowerCase();
  if (u.length < 3 || u.length > 40) {
    return "Username must be between 3 and 40 characters.";
  }
  if (u.includes("--")) {
    return "Username cannot contain consecutive hyphens.";
  }
  if (!USERNAME_RE.test(u)) {
    return "Use lowercase letters, numbers, hyphens, and underscores; start and end with a letter or number.";
  }
  if (RESERVED_USERNAMES.has(u)) {
    return "That username is reserved.";
  }
  return null;
}

export default function AuthPage({ mode }: Props) {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const { user, login, signup } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";
  // Live username validation (signup only) for inline feedback.
  const usernameError = isSignup && username ? validateUsername(username) : null;

  useEffect(() => {
    if (user) {
      const next = new URLSearchParams(window.location.search).get("next") || "/account/pads";
      navigate(next.startsWith("/") ? next : "/account/pads", { replace: true });
    }
  }, [navigate, user]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (isSignup) {
      const uErr = validateUsername(username);
      if (uErr) {
        setError(uErr);
        return;
      }
    }
    setBusy(true);
    try {
      if (isSignup) {
        // Server stores usernames normalized (lowercase); send it that way.
        await signup(
          email,
          password,
          username.trim().toLowerCase(),
          displayName || undefined
        );
      } else {
        await login(email, password);
      }
      const next = new URLSearchParams(window.location.search).get("next") || "/";
      navigate(next.startsWith("/") ? next : "/", { replace: true });
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
            <span>Username</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value.toLowerCase())}
              required
              minLength={3}
              maxLength={40}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              aria-invalid={usernameError ? true : undefined}
              placeholder="yourname"
            />
            <small className="auth-hint">
              {usernameError ? (
                <span className="error">{usernameError}</span>
              ) : (
                <>This becomes your pad address: <code>{username || "yourname"}/padname</code></>
              )}
            </small>
          </label>
        )}

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

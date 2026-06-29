import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ThemeToggle from "../components/ThemeToggle";
import { createPad } from "../api";
import { useTheme } from "../useTheme";

export default function Landing() {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startPad() {
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const pad = await createPad();
      navigate(`/${pad.slug}`);
    } catch (e) {
      setCreating(false);
      setError((e as Error).message);
    }
  }

  return (
    <div className="landing">
      <header className="landing-header">
        <Link to="/" className="wordmark" aria-label="River home">
          River
        </Link>
        <nav className="landing-nav">
          <a href="#how">How it works</a>
          <Link to="/login">Sign in</Link>
          <ThemeToggle theme={theme} onToggle={toggle} />
        </nav>
      </header>

      <main className="landing-main">
        <section className="hero">
          <p className="hero-eyebrow">Collaborative scratchpad</p>
          <h1 className="hero-title">
            Open a page.
            <br />
            Start typing.
            <br />
            Hand someone the door.
          </h1>
          <p className="hero-sub">
            River is a shared page you can open in a second and write on together
            in real time. No setup, no documents to manage — just a link.
          </p>
          <div className="hero-cta">
            <button
              type="button"
              className="btn btn-primary"
              onClick={startPad}
              disabled={creating}
            >
              {creating ? "Opening…" : "Start a pad — it's instant"}
            </button>
            <span className="hero-note">No signup required.</span>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </section>

        <section className="how" id="how">
          <div className="how-grid">
            <div className="how-col">
              <p className="how-num">01</p>
              <h3>Open instantly</h3>
              <p>
                Hit start and you're writing on a fresh pad — no account, no
                blank-document ceremony.
              </p>
            </div>
            <div className="how-col">
              <p className="how-num">02</p>
              <h3>Write together</h3>
              <p>
                Share the link and edits sync live between everyone on the pad,
                cursors and all.
              </p>
            </div>
            <div className="how-col">
              <p className="how-num">03</p>
              <h3>Lock it down</h3>
              <p>
                Keep a pad with an account, set a PIN, or make it invite-only when
                it matters.
              </p>
            </div>
          </div>
        </section>

        <section className="preview-section">
          <div className="preview-copy">
            <h2>A page that gets out of the way</h2>
            <p>
              Plain text, files, and live cursors on a calm, distraction-free
              surface. The writing is the interface.
            </p>
          </div>
          <div className="preview-card" aria-hidden="true">
            <div className="preview-bar">
              <span className="preview-slug">river.app/quiet-harbor-07</span>
              <span className="preview-dots">
                <i />
                <i />
                <i />
              </span>
            </div>
            <div className="preview-body">
              <h4>Sprint notes</h4>
              <p>— ship the walnut theme</p>
              <p>— review the editor surface</p>
              <p>
                — hand off to design<span className="preview-caret" />
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-inner">
          <span className="wordmark wordmark--sm">River</span>
          <nav className="landing-footer-links">
            <a href="#">Privacy</a>
            <a href="#">Terms</a>
            <a href="#">Help</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

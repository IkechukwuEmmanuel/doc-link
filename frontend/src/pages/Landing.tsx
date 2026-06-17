import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import ThemeToggle from "../components/ThemeToggle";
import { createPad } from "../api";
import { randomExampleSlug } from "../exampleSlug";
import { useTheme } from "../useTheme";

export default function Landing() {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const [example, setExample] = useState(randomExampleSlug);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const startedRef = useRef(false);

  // Rotate the illustrative example slug gently (ambient, not decorative motion).
  useEffect(() => {
    const id = setInterval(() => setExample(randomExampleSlug()), 2500);
    return () => clearInterval(id);
  }, []);

  // The element IS the create action: click or first keystroke creates the pad
  // and transitions continuously, carrying any buffered text into the new pad.
  async function start(seed: string) {
    if (startedRef.current) return;
    startedRef.current = true;
    setCreating(true);
    setError(null);
    try {
      const pad = await createPad();
      navigate(`/${pad.slug}`, { state: { seed } });
    } catch (e) {
      startedRef.current = false;
      setCreating(false);
      setError((e as Error).message);
    }
  }

  return (
    <main className="landing">
      <div className="landing-corner">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>

      <div className="landing-center">
        <textarea
          ref={inputRef}
          className="hero-input"
          aria-label="Start a new pad — type or click to begin"
          rows={1}
          spellCheck={false}
          autoFocus
          placeholder="Start typing…"
          onClick={() => start("")}
          onChange={(e) => start(e.target.value)}
          disabled={creating}
        />
        <p className="hero-example" aria-hidden="true">
          spacepad.app/<span className="hero-slug">{example}</span>
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>

      <a className="landing-login" href="/login">
        Log in
      </a>
    </main>
  );
}

import { Link } from "react-router-dom";
import ThemeToggle from "../components/ThemeToggle";
import { useTheme } from "../useTheme";

export default function Terms() {
  const { theme, toggle } = useTheme();
  return (
    <main className="static-page">
      <div className="landing-corner">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>
      <div className="static-card">
        <h1>Terms</h1>
        <p>This is a minimal terms of service placeholder. Replace with full text.</p>
        <p>
          <Link className="text-link" to="/">
            ← Back home
          </Link>
        </p>
      </div>
    </main>
  );
}

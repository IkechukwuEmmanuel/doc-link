import { Link } from "react-router-dom";
import ThemeToggle from "../components/ThemeToggle";
import { useTheme } from "../useTheme";

export default function Privacy() {
  const { theme, toggle } = useTheme();
  return (
    <main className="static-page">
      <div className="landing-corner">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>
      <div className="static-card">
        <h1>Privacy</h1>
        <p>This is a minimal privacy page placeholder. Add your policy text here.</p>
        <p>
          <Link className="text-link" to="/">
            ← Back home
          </Link>
        </p>
      </div>
    </main>
  );
}

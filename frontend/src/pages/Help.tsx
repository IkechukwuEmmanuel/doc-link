import { Link } from "react-router-dom";
import ThemeToggle from "../components/ThemeToggle";
import { useTheme } from "../useTheme";

export default function Help() {
  const { theme, toggle } = useTheme();
  return (
    <main className="static-page">
      <div className="landing-corner">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>
      <div className="static-card">
        <h1>Help</h1>
        <p>Need help? This page should link to documentation and support channels.</p>
        <p>
          <Link className="text-link" to="/">
            ← Back home
          </Link>
        </p>
      </div>
    </main>
  );
}

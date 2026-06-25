import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createPad } from "../api";

export default function NewPad() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Create a pad anonymously and redirect to its slug.
    // Mirrors the behavior of the Landing page's create action.
    createPad(undefined, undefined)
      .then((pad) => navigate(`/${pad.slug}`))
      .catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // In case of error, show a simple message.
  if (error) {
    return (
      <div className="pad-state">
        <p className="error" role="alert">{error}</p>
        <a className="text-link" href="/">← Home</a>
      </div>
    );
  }
  // While creating, show a basic loading placeholder.
  return <div className="pad-state" aria-busy="true" />;
}

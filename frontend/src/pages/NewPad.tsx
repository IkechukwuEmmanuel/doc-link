import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { createPad } from "../api";
import { useAuth } from "../auth";

export default function NewPad() {
  const navigate = useNavigate();
  const { user, authedFetch } = useAuth();
  const { customName } = useParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Create a pad and redirect to its address.
    // If authenticated, the pad is owned by the user.
    // If a custom name is provided, use it as the pad name.
    // If signed in, use the authenticated fetcher so the pad is owned by the user.
    createPad(customName, user ? authedFetch : undefined)
      .then((pad) => {
        // Determine the redirect URL based on ownership
        let redirectUrl: string;
        if (pad.owner_id && user) {
          // Owned pad: redirect to /{username}/{slug or custom name}
          redirectUrl = `/${user.username}/${pad.name || pad.slug}`;
        } else {
          // Anonymous pad: redirect to /{slug}
          redirectUrl = `/${pad.slug}`;
        }
        navigate(redirectUrl);
      })
      .catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // In case of error, show a simple message.
  if (error) {
    return (
      <div className="pad-state">
        <p className="error" role="alert">{error}</p>
        <Link className="text-link" to="/">← Home</Link>
      </div>
    );
  }
  // While creating, show a basic loading placeholder.
  return <div className="pad-state" aria-busy="true" />;
}

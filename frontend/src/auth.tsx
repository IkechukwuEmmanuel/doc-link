import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

export interface AuthUser {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  email_verified: boolean;
  created_at: string;
}

interface AuthResponse {
  access_token: string;
  user: AuthUser;
}

interface AuthContextValue {
  user: AuthUser | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    email: string,
    password: string,
    displayName?: string
  ) => Promise<void>;
  logout: () => Promise<void>;
  authedFetch: (input: string, init?: RequestInit) => Promise<Response>;
  // Current in-memory access token (for the WebSocket handshake, which can't
  // set an Authorization header). May be null when signed out.
  getAccessToken: () => string | null;
  // Re-fetch the current user (e.g. after email verification flips a flag).
  reloadUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function readError(resp: Response, fallback: string): Promise<string> {
  const body = await resp.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : fallback;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);
  // Access token lives only in memory (refresh token is an httpOnly cookie).
  const accessToken = useRef<string | null>(null);

  const applyAuth = useCallback((data: AuthResponse) => {
    accessToken.current = data.access_token;
    setUser(data.user);
  }, []);

  const refresh = useCallback(async (): Promise<boolean> => {
    const resp = await fetch("/api/auth/refresh", { method: "POST" });
    if (!resp.ok) {
      accessToken.current = null;
      setUser(null);
      return false;
    }
    applyAuth(await resp.json());
    return true;
  }, [applyAuth]);

  // Bootstrap session from the refresh cookie on first load.
  useEffect(() => {
    refresh().finally(() => setReady(true));
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!resp.ok) throw new Error(await readError(resp, "Login failed."));
      applyAuth(await resp.json());
    },
    [applyAuth]
  );

  const signup = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const resp = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          display_name: displayName || null,
        }),
      });
      if (!resp.ok) throw new Error(await readError(resp, "Signup failed."));
      applyAuth(await resp.json());
    },
    [applyAuth]
  );

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    accessToken.current = null;
    setUser(null);
  }, []);

  const getAccessToken = useCallback(() => accessToken.current, []);

  // Fetch wrapper that attaches the access token and retries once after a
  // transparent refresh on 401.
  const authedFetch = useCallback(
    async (input: string, init: RequestInit = {}): Promise<Response> => {
      const withAuth = (token: string | null): RequestInit => ({
        ...init,
        headers: {
          ...(init.headers || {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      let resp = await fetch(input, withAuth(accessToken.current));
      if (resp.status === 401 && (await refresh())) {
        resp = await fetch(input, withAuth(accessToken.current));
      }
      return resp;
    },
    [refresh]
  );

  const reloadUser = useCallback(async () => {
    const resp = await authedFetch("/api/auth/me");
    if (resp.ok) setUser(await resp.json());
  }, [authedFetch]);

  return (
    <AuthContext.Provider
      value={{
        user,
        ready,
        login,
        signup,
        logout,
        authedFetch,
        getAccessToken,
        reloadUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

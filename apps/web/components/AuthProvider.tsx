"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { API_BASE, getAccount } from "@/lib/api";
import { supabase, supabaseConfigured } from "@/lib/supabase";

/**
 * One place that knows who the user is.
 *
 * Everything that spends money — unlock, batch, account — reads its token
 * from here. Nothing else in the app talks to Supabase, so swapping the
 * provider is a change to this file and `lib/supabase.ts`.
 *
 * Sign-in is a **magic link**. No password to store, reset, leak or get
 * wrong, and the click is itself proof of the address — which is what the
 * API relies on before it will link a session to an existing account.
 *
 * `dev` mode exists so the whole signed-in flow runs without a Supabase
 * project. It is gated on an explicit env var here and, independently, on
 * the API refusing to mount the route outside development.
 */

export type AuthMode = "supabase" | "dev" | "none";

type AuthState = {
  mode: AuthMode;
  token: string | null;
  email: string | null;
  loading: boolean;
  signedIn: boolean;
  /** Resolves to the message to show the user, or throws. */
  signIn: (email: string) => Promise<string>;
  signOut: () => Promise<void>;
  /** Shared so the header and the download panel cannot disagree. */
  credits: number | null;
  refreshCredits: () => Promise<void>;
};

const DEV_AUTH = process.env.NEXT_PUBLIC_DEV_AUTH === "1";
const DEV_KEY = "v4u.dev-session";

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth used outside AuthProvider");
  return value;
}

/**
 * The signed-in credit balance.
 *
 * Context rather than a per-component fetch: the header and the download
 * panel both show it, and two different numbers on one page is worse than
 * none. It also has to be refreshed after an unlock — a header still
 * showing the pre-purchase balance reads as "my credit was not taken".
 */
export function useCredits(): number | null {
  return useAuth().credits;
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const mode: AuthMode = supabaseConfigured ? "supabase" : DEV_AUTH ? "dev" : "none";
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(mode !== "none");
  const [credits, setCredits] = useState<number | null>(null);

  useEffect(() => {
    if (mode === "none") {
      setLoading(false);
      return;
    }

    if (mode === "dev") {
      try {
        const saved = window.localStorage.getItem(DEV_KEY);
        if (saved) {
          const parsed = JSON.parse(saved) as { token: string; email: string; expires: number };
          if (parsed.expires > Date.now()) {
            setToken(parsed.token);
            setEmail(parsed.email);
          } else {
            window.localStorage.removeItem(DEV_KEY);
          }
        }
      } catch {
        /* a corrupt dev session is not worth a crash */
      }
      setLoading(false);
      return;
    }

    let cancelled = false;
    let unsubscribe: (() => void) | null = null;

    void (async () => {
      const client = await supabase();
      if (cancelled) return;

      const { data } = await client.auth.getSession();
      if (!cancelled) {
        setToken(data.session?.access_token ?? null);
        setEmail(data.session?.user?.email ?? null);
        setLoading(false);
      }

      // Fires on sign-in, sign-out and — importantly — on every token
      // refresh. Holding the first access token would start handing the
      // API an expired one about an hour in.
      const listener = client.auth.onAuthStateChange((_event, session) => {
        setToken(session?.access_token ?? null);
        setEmail(session?.user?.email ?? null);
        setLoading(false);
      });
      unsubscribe = () => listener.data.subscription.unsubscribe();
      if (cancelled) unsubscribe();
    })();

    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [mode]);

  const refreshCredits = useCallback(async () => {
    if (!token) {
      setCredits(null);
      return;
    }
    try {
      setCredits((await getAccount(token)).credits);
    } catch {
      // A failed balance read must not break the page it decorates.
      setCredits(null);
    }
  }, [token]);

  useEffect(() => {
    void refreshCredits();
  }, [refreshCredits]);

  const signIn = useCallback(
    async (address: string): Promise<string> => {
      if (mode === "dev") {
        const response = await fetch(`${API_BASE}/v1/dev/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: address }),
        });
        if (!response.ok) throw new Error("development sign-in is not enabled on the API");
        const body = (await response.json()) as {
          access_token: string;
          email: string;
          expires_in: number;
        };
        setToken(body.access_token);
        setEmail(body.email);
        window.localStorage.setItem(
          DEV_KEY,
          JSON.stringify({
            token: body.access_token,
            email: body.email,
            expires: Date.now() + body.expires_in * 1000,
          }),
        );
        return `Signed in as ${body.email} (development mode — not real authentication).`;
      }

      if (mode !== "supabase") {
        throw new Error("sign-in is not configured");
      }

      const client = await supabase();
      const { error } = await client.auth.signInWithOtp({
        email: address,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
      });
      if (error) throw new Error(error.message);
      return `Check ${address} for a sign-in link. It expires in an hour.`;
    },
    [mode],
  );

  const signOut = useCallback(async () => {
    if (mode === "dev") {
      window.localStorage.removeItem(DEV_KEY);
    } else if (mode === "supabase") {
      const client = await supabase();
      await client.auth.signOut();
    }
    setToken(null);
    setEmail(null);
    setCredits(null);
  }, [mode]);

  const value = useMemo<AuthState>(
    () => ({
      mode,
      token,
      email,
      loading,
      signedIn: Boolean(token),
      signIn,
      signOut,
      credits,
      refreshCredits,
    }),
    [mode, token, email, loading, signIn, signOut, credits, refreshCredits],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "./AuthProvider";
import SignIn from "./SignIn";
import { Notice } from "./ui";

/**
 * The standalone sign-in page.
 *
 * Two things the bare form does not do on its own: explain a magic link
 * that failed, and get out of the way once the session exists. Landing on
 * a sign-in page that says "signed in" is a dead end — dev sign-in is
 * instant, and a Supabase session can also already be present when someone
 * navigates here by hand.
 */
export default function SignInScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const { signedIn, loading } = useAuth();
  const error = params.get("error");
  const next = params.get("next") ?? "/account";

  useEffect(() => {
    if (signedIn) router.replace(next);
  }, [signedIn, next, router]);

  if (signedIn) {
    return <p role="status">Signed in. Taking you to your account…</p>;
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      {error && (
        <Notice tone="magenta" title="That link didn't work">
          {error}. Links expire after an hour and can only be used once — ask for a new one.
        </Notice>
      )}
      {!loading && <SignIn />}
    </div>
  );
}

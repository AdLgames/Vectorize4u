"use client";

import { useState } from "react";
import { useAuth } from "./AuthProvider";
import { Button, Card, Muted, Notice } from "./ui";

/**
 * Sign-in: one field, no password.
 *
 * A magic link means nothing to store, reset or leak, and the click proves
 * the address — which is what the API requires before it will attach a
 * session to an existing account.
 */

export default function SignIn({
  reason,
  compact = false,
}: {
  reason?: string;
  compact?: boolean;
}) {
  const { mode, signIn, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (mode === "none") {
    return (
      <Notice tone="amber" title="Sign-in isn't configured">
        Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
        <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code>, or run with{" "}
        <code>NEXT_PUBLIC_DEV_AUTH=1</code> against an API started with{" "}
        <code>VEC_DEV_AUTH_ENABLED=1</code>. See docs/runbook.md.
      </Notice>
    );
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      setStatus(await signIn(email.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <form onSubmit={submit} style={{ display: "grid", gap: "var(--space-3)" }}>
        <div>
          <div style={{ fontWeight: 600, color: "var(--ink-900)" }}>
            {reason ?? "Sign in"}
          </div>
          {!compact && (
            <Muted size="sm">
              {mode === "dev"
                ? "Development mode: any address signs you straight in. This is not real authentication."
                : "We'll email you a link. No password to remember."}
            </Muted>
          )}
        </div>

        <label htmlFor="signin-email" style={{ display: "grid", gap: 6 }}>
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>Email</span>
          <input
            id="signin-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@studio.com"
            style={{
              padding: "10px 12px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--ink-200)",
              background: "var(--ink-0)",
              color: "var(--ink-900)",
              fontSize: "var(--text-base)",
            }}
          />
        </label>

        <Button type="submit" variant="primary" full disabled={busy || loading}>
          {busy ? "Sending…" : mode === "dev" ? "Sign in (dev)" : "Email me a link"}
        </Button>

        {status && (
          <Notice tone="green" title="Sent">
            {status}
          </Notice>
        )}
        {error && (
          <Notice tone="magenta" title="Couldn't sign you in">
            {error}
          </Notice>
        )}
      </form>
    </Card>
  );
}

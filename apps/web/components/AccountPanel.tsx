"use client";

import { useEffect, useState } from "react";
import { type Account, ApiError, getAccount } from "@/lib/api";
import { Button, Card, Meter, Muted } from "./ui";

/**
 * Credits are shown **per grant, with expiry**.
 *
 * A single balance cannot express "100 downloads that expire at period end"
 * alongside "50 that never expire" (§5), and showing only the total is how
 * people are surprised when credits lapse. The consumption rule — soonest
 * -expiring first — is stated where it matters, next to the numbers.
 */

const SOURCE_LABEL: Record<string, string> = {
  free_monthly: "Free monthly",
  plan_monthly: "Plan allowance",
  api_monthly: "API allowance",
  pack: "Credit pack",
  promo: "Promotion",
};

export default function AccountPanel() {
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [token] = useState<string | null>(null); // wired to the auth provider in Phase 4

  useEffect(() => {
    if (!token) return;
    getAccount(token)
      .then(setAccount)
      .catch((err) => setError(err instanceof ApiError ? err.problem.detail : "Failed to load"));
  }, [token]);

  if (!token) {
    return (
      <Card>
        <p style={{ margin: 0, color: "var(--ink-500)" }}>
          Sign in to see your downloads, when your credits expire, and your conversion history.
        </p>
      </Card>
    );
  }
  if (error) {
    return (
      <p role="alert" style={{ color: "var(--magenta)" }}>
        {error}
      </p>
    );
  }
  if (!account) return <p role="status">Loading…</p>;

  const plan = account.grants.find((g) => g.source === "plan_monthly" || g.source === "free_monthly");
  const pack = account.grants.find((g) => g.source === "pack");

  return (
    <div style={{ display: "grid", gap: "var(--space-6)" }}>
      <div
        style={{
          display: "grid",
          gap: "var(--space-4)",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
        }}
      >
        <Card>
          <Muted size="xs">Downloads this month</Muted>
          <div style={{ fontSize: "var(--text-h2)", fontWeight: 600, color: "var(--ink-900)" }}>
            {plan ? plan.amount - plan.remaining : 0}{" "}
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-400)", fontWeight: 400 }}>
              of {plan?.amount ?? 0}
            </span>
          </div>
          <div style={{ marginTop: 8 }}>
            <Meter
              value={plan && plan.amount ? (plan.amount - plan.remaining) / plan.amount : 0}
              label="Monthly downloads used"
            />
          </div>
          <div style={{ marginTop: 6 }}>
            <Muted size="xs">
              {account.plan === "free" ? "Free" : account.plan}
              {plan?.expires_at
                ? ` · resets ${new Date(plan.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "long" })}`
                : ""}
            </Muted>
          </div>
        </Card>

        <Card>
          <Muted size="xs">Credit pack balance</Muted>
          <div style={{ fontSize: "var(--text-h2)", fontWeight: 600, color: "var(--ink-900)" }}>
            {pack?.remaining ?? 0}{" "}
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-400)", fontWeight: 400 }}>
              of {pack?.amount ?? 0}
            </span>
          </div>
          <div style={{ marginTop: 8 }}>
            <Meter
              value={pack && pack.amount ? pack.remaining / pack.amount : 0}
              tone="green"
              label="Credit pack remaining"
            />
          </div>
          <div style={{ marginTop: 6 }}>
            <Muted size="xs">
              Never expires. Used after your monthly downloads run out.
            </Muted>
          </div>
        </Card>

        <Card>
          <Muted size="xs">Billing</Muted>
          <div style={{ marginTop: 6, color: "var(--ink-900)" }}>{account.email}</div>
          <div style={{ marginTop: 4 }}>
            <Muted size="xs">
              {account.usage_30d.jobs} conversions and {account.usage_30d.credits} downloads in
              the last 30 days.
            </Muted>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: "var(--space-3)", flexWrap: "wrap" }}>
            <Button size="sm">Buy 50 credits</Button>
            <Button size="sm">Manage plan</Button>
          </div>
        </Card>
      </div>

      <section style={{ display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h3)", margin: 0 }}>Where your credits came from</h2>
        <Card padded={false}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-sm)" }}>
            <thead>
              <tr style={{ color: "var(--ink-500)", fontSize: "var(--text-xs)", textAlign: "left" }}>
                <th style={cell}>Source</th>
                <th style={cell}>Remaining</th>
                <th style={cell}>Expires</th>
              </tr>
            </thead>
            <tbody>
              {account.grants.map((grant) => (
                <tr key={grant.id} style={{ borderTop: "1px solid var(--ink-100)" }}>
                  <td style={cell}>{SOURCE_LABEL[grant.source] ?? grant.source}</td>
                  <td style={cell}>
                    {grant.remaining} / {grant.amount}
                  </td>
                  <td style={cell}>
                    {grant.expires_at
                      ? new Date(grant.expires_at).toLocaleDateString()
                      : "never"}
                  </td>
                </tr>
              ))}
              {account.grants.length === 0 && (
                <tr>
                  <td style={cell} colSpan={3}>
                    <Muted size="xs">No credits yet.</Muted>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
        <Muted size="xs">
          Credits that expire soonest are always spent first, so nothing lapses while you still
          have never-expiring credit.
        </Muted>
      </section>
    </div>
  );
}

const cell: React.CSSProperties = { padding: "10px 14px" };

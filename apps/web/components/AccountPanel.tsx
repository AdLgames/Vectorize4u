"use client";

import { useEffect, useState } from "react";
import { type Account, ApiError, getAccount } from "@/lib/api";

/**
 * Credits are shown **per grant**, with expiry, because a single number
 * cannot express "100 downloads that expire at period end" alongside "50
 * that never expire" (§5). Showing only a total is how people are surprised
 * when credits lapse.
 */

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
      <p className="rounded bg-slate-100 p-4 text-sm dark:bg-slate-800">
        Sign in to see your downloads, credit expiry and usage.
      </p>
    );
  }
  if (error) return <p role="alert">{error}</p>;
  if (!account) return <p role="status">Loading…</p>;

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Plan</h2>
        <p className="capitalize">{account.plan}</p>
        <p className="text-3xl font-semibold tabular-nums">{account.credits}</p>
        <p className="text-sm text-slate-500 dark:text-slate-400">downloads remaining</p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Where those credits came from</h2>
        <table className="w-full text-left text-sm">
          <thead className="text-slate-500 dark:text-slate-400">
            <tr>
              <th scope="col" className="py-1">Source</th>
              <th scope="col" className="py-1">Remaining</th>
              <th scope="col" className="py-1">Expires</th>
            </tr>
          </thead>
          <tbody>
            {account.grants.map((grant) => (
              <tr key={grant.id} className="border-t border-slate-200 dark:border-slate-700">
                <td className="py-1">{grant.source.replace(/_/g, " ")}</td>
                <td className="py-1 tabular-nums">
                  {grant.remaining} / {grant.amount}
                </td>
                <td className="py-1">
                  {grant.expires_at ? new Date(grant.expires_at).toLocaleDateString() : "never"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Credits that expire soonest are always spent first, so nothing lapses while
          you still have never-expiring credit.
        </p>
      </section>

      <section className="space-y-1">
        <h2 className="text-lg font-semibold">Last 30 days</h2>
        <p className="text-sm">
          {account.usage_30d.jobs} conversions · {account.usage_30d.credits} downloads
        </p>
      </section>
    </div>
  );
}

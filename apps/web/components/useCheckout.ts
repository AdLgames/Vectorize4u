"use client";

import { useCallback, useState } from "react";
import { ApiError, openBillingPortal, startCheckout } from "@/lib/api";
import { useAuth } from "./AuthProvider";

/**
 * Sends the browser to Stripe.
 *
 * Shared because three places start a purchase — the pricing section, the
 * account page and the "out of credits" message — and each needs the same
 * two behaviours: bounce to sign-in first if there is no session, and say
 * something useful when billing is not configured rather than failing
 * silently.
 */
export function useCheckout() {
  const { token, signedIn } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const buy = useCallback(
    async (plan: string) => {
      if (!signedIn || !token) {
        // Purchases are attached to an account, so there is nothing to do
        // until there is one. Come back to the price list afterwards.
        window.location.href = `/signin?next=${encodeURIComponent("/#pricing")}`;
        return;
      }
      setBusy(plan);
      setError(null);
      try {
        window.location.href = await startCheckout(plan, token);
      } catch (err) {
        setBusy(null);
        setError(
          err instanceof ApiError && err.problem.error_code === "billing_unavailable"
            ? "Payments aren't switched on yet. Nothing was charged."
            : err instanceof ApiError
              ? err.problem.detail
              : "Couldn't start checkout.",
        );
      }
    },
    [signedIn, token],
  );

  const manage = useCallback(async () => {
    if (!token) return;
    setBusy("portal");
    setError(null);
    try {
      window.location.href = await openBillingPortal(token);
    } catch (err) {
      setBusy(null);
      setError(
        err instanceof ApiError && err.problem.error_code === "no_billing_account"
          ? "You haven't bought anything yet, so there's no billing to manage."
          : "Couldn't open the billing portal.",
      );
    }
  }, [token]);

  return { buy, manage, busy, error };
}

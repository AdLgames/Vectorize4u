"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "./AuthProvider";
import { Button, Card, Muted } from "./ui";

/**
 * Where Stripe sends the browser after paying.
 *
 * This page grants nothing and must not pretend to. The credits arrive
 * when the webhook does, which is usually immediate but is a *separate*
 * event — so the page polls the real balance rather than asserting a
 * number it cannot know, and says plainly what is happening if the balance
 * has not moved yet.
 */
export default function CheckoutSuccess() {
  const { signedIn, credits, refreshCredits } = useAuth();
  const [waited, setWaited] = useState(0);
  const arrived = credits !== null && credits > 0;

  useEffect(() => {
    if (!signedIn || arrived || waited > 12) return;
    const timer = setTimeout(() => {
      void refreshCredits();
      setWaited((n) => n + 1);
    }, 1500);
    return () => clearTimeout(timer);
  }, [signedIn, arrived, waited, refreshCredits]);

  return (
    <Card>
      <h1 style={{ fontSize: "var(--text-h2)", margin: "0 0 8px" }}>
        {arrived ? "Payment received" : "Payment received — adding your credits"}
      </h1>

      {arrived ? (
        <p style={{ color: "var(--ink-500)", margin: "0 0 var(--space-4)" }}>
          You have <strong>{credits}</strong> {credits === 1 ? "download" : "downloads"}{" "}
          available. A receipt is on its way from Stripe.
        </p>
      ) : (
        <p style={{ color: "var(--ink-500)", margin: "0 0 var(--space-4)" }}>
          Stripe has taken the payment and we are waiting for it to confirm. This is
          normally a second or two.{" "}
          {waited > 8 && (
            <>
              It is taking longer than usual — your payment is safe and the credits will
              appear. If they have not within a few minutes, get in touch and quote your
              email address.
            </>
          )}
        </p>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Link href="/convert" style={{ textDecoration: "none" }}>
          <Button variant="primary">Convert something</Button>
        </Link>
        <Link href="/account" style={{ textDecoration: "none" }}>
          <Button>See your account</Button>
        </Link>
      </div>

      {!signedIn && (
        <div style={{ marginTop: "var(--space-3)" }}>
          <Muted size="xs">
            Sign in to see the credits on your account.
          </Muted>
        </div>
      )}
    </Card>
  );
}

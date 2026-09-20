"use client";

import { Button, Notice } from "./ui";
import { useCheckout } from "./useCheckout";

/**
 * §10's open decision, resolved.
 *
 * The market anchor is unlimited web downloads at about $9.99/month, and a
 * capped $12 Starter loses a straight price comparison. The answer taken
 * here is option (a): keep the prices, and lead with the **credit pack** —
 * the one clear gap in the competitor's line-up — while the plan cards
 * carry the things a subscription actually buys (batch size, priority).
 *
 * Most traffic is a person with a single logo who will never subscribe.
 * Without the one-off pack we monetize none of them.
 */

export const PLANS: {
  planId: string | null;
  name: string;
  note: string;
  price: string;
  per: string;
  detail: string;
  cta: string;
  highlight: boolean;
}[] = [
  {
    planId: null,
    name: "Free",
    note: "no card needed",
    price: "$0",
    per: "",
    detail: "Watermarked previews, 3 downloads a month, one file at a time",
    cta: "Start free",
    highlight: false,
  },
  {
    planId: "pack",
    name: "Credit pack",
    note: "one-off",
    price: "$9",
    per: "",
    detail: "50 downloads that never expire. Every format, including DXF. No subscription.",
    cta: "Buy 50 credits",
    highlight: true,
  },
  {
    planId: "starter",
    name: "Starter",
    note: "",
    price: "$12",
    per: "/mo",
    detail: "100 downloads a month, every format, batches up to 25 files",
    cta: "Choose Starter",
    highlight: false,
  },
  {
    planId: "pro",
    name: "Pro",
    note: "",
    price: "$29",
    per: "/mo",
    detail: "1,000 downloads a month, batches up to 500, priority queue",
    cta: "Choose Pro",
    highlight: false,
  },
];

export default function Pricing() {
  const { buy, busy, error } = useCheckout();

  return (
    <section
      id="pricing"
      aria-labelledby="pricing-heading"
      style={{ display: "grid", gap: "var(--space-4)" }}
    >
      <h2 id="pricing-heading" style={{ fontSize: "var(--text-h2)", margin: 0 }}>
        Pricing
      </h2>
      <p style={{ color: "var(--ink-500)", margin: 0, maxWidth: "48ch" }}>
        Previews are always free. You pay when you download a file without a watermark.
      </p>
      <div
        style={{
          display: "grid",
          gap: "var(--space-4)",
          gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
        }}
      >
        {PLANS.map((plan) => (
          <div
            key={plan.name}
            style={{
              border: "1px solid var(--ink-100)",
              borderTop: `3px solid ${plan.highlight ? "var(--cyan)" : "transparent"}`,
              borderRadius: "var(--radius-lg)",
              background: plan.highlight ? "var(--ink-25)" : "var(--ink-0)",
              padding: "var(--space-5)",
              display: "grid",
              gap: "var(--space-3)",
              alignContent: "start",
            }}
          >
            <div>
              <div style={{ fontWeight: 600, color: "var(--ink-900)" }}>{plan.name}</div>
              {plan.note && (
                <div
                  style={{
                    fontSize: "var(--text-xs)",
                    color: plan.highlight ? "var(--cyan-strong)" : "var(--ink-500)",
                  }}
                >
                  {plan.note}
                </div>
              )}
            </div>
            <div style={{ fontSize: "var(--text-h2)", fontWeight: 600, color: "var(--ink-900)" }}>
              {plan.price}
              <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-500)", fontWeight: 400 }}>
                {plan.per}
              </span>
            </div>
            <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-500)", margin: 0 }}>
              {plan.detail}
            </p>
            <Button
              variant={plan.highlight ? "primary" : "secondary"}
              full
              disabled={busy !== null || !plan.planId}
              onClick={plan.planId ? () => void buy(plan.planId as string) : undefined}
            >
              {/* `busy === plan.planId` alone is a trap: Free has no plan id,
                  so null === null made its button permanently read as
                  mid-purchase. */}
              {plan.planId !== null && busy === plan.planId
                ? "Taking you to Stripe…"
                : plan.cta}
            </Button>
          </div>
        ))}
      </div>
      {error && (
        <Notice tone="magenta" title="Couldn't start checkout">
          {error}
        </Notice>
      )}
      <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)", margin: 0 }}>
        Formats are never gated on paid plans. DXF is the reason cutter users show up; putting
        it behind the top tier would be a trick.
      </p>
    </section>
  );
}

import type { Metadata } from "next";
import Link from "next/link";
import { Card } from "@/components/ui";

/**
 * §9 — "tutorial content aimed at buyers". Not general vector theory:
 * three specific jobs that someone is doing today and getting wrong for a
 * reason we can name.
 */

export const metadata: Metadata = {
  title: "Guides",
  description:
    "Practical guides for print shops, cutters and laser users: preparing a logo for DTF, rescuing a low-res logo, and fixing DXF scale in LightBurn.",
  alternates: { canonical: "/guides" },
};

const GUIDES = [
  {
    href: "/guides/prepare-a-logo-for-dtf-printing",
    title: "Prepare a logo for DTF printing",
    blurb:
      "The white underbase is generated from your alpha channel, so every transparency decision in the file becomes a physical one. Four problems, in the order they bite.",
  },
  {
    href: "/guides/clean-up-a-low-res-logo",
    title: "Clean up a customer's low-res logo",
    blurb:
      "The 240-pixel logo from a social profile that needs to be on a banner by Thursday. What to ask for first, what to trace, and when to redraw instead.",
  },
  {
    href: "/guides/fix-dxf-scale-in-lightburn",
    title: "Fix DXF scale in LightBurn",
    blurb:
      "If the wrong size divides neatly by 25.4, it is units and nothing else. Fix this file in under a minute, then fix the export so it stops happening.",
  },
];

export default function GuidesPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-6)" }}>
      <div style={{ maxWidth: "62ch", display: "grid", gap: "var(--space-3)" }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Guides</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Specific jobs, written for the people doing them — print shops, cutters and laser
          users — rather than general advice about vectors.
        </p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: "var(--space-4)",
        }}
      >
        {GUIDES.map((guide) => (
          <Card key={guide.href}>
            <h2 style={{ fontSize: "var(--text-h3)", margin: "0 0 8px" }}>
              <Link href={guide.href} style={{ color: "var(--ink-900)", textDecoration: "none" }}>
                {guide.title}
              </Link>
            </h2>
            <p style={{ color: "var(--ink-500)", margin: 0, fontSize: "var(--text-sm)" }}>
              {guide.blurb}
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}

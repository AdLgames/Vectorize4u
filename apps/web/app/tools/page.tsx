import type { Metadata } from "next";
import Link from "next/link";
import { Card } from "@/components/ui";

/**
 * §9 — free tools as link bait. They are free because they run entirely in
 * the visitor's browser: no upload, no queue, no cost to us, and an honest
 * privacy answer for someone pasting a client's artwork.
 */

export const metadata: Metadata = {
  title: "Free SVG tools",
  description:
    "Free, browser-only tools for vector work: minify an SVG, convert SVG to PNG, and pull the palette out of an image. Nothing is uploaded.",
  alternates: { canonical: "/tools" },
};

const TOOLS = [
  {
    href: "/tools/svg-minifier",
    title: "SVG minifier",
    blurb:
      "Strip editor metadata, unreferenced ids and excess decimal places, with before-and-after rendered side by side so you can see nothing broke.",
  },
  {
    href: "/tools/svg-to-png",
    title: "SVG to PNG",
    blurb:
      "Rasterise an SVG at any width, with or without a transparent background, for places that still refuse vector files.",
  },
  {
    href: "/tools/palette-extractor",
    title: "Palette extractor",
    blurb:
      "Pull the dominant colours out of any image as hex values, with the share of the image each one covers.",
  },
];

export default function ToolsPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-6)" }}>
      <div style={{ maxWidth: "62ch", display: "grid", gap: "var(--space-3)" }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Free tools</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Small jobs that should not need an account, a queue or an upload. These run
          entirely in your browser — the files never reach our servers, which is also why
          they are free.
        </p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: "var(--space-4)",
        }}
      >
        {TOOLS.map((tool) => (
          <Card key={tool.href}>
            <h2 style={{ fontSize: "var(--text-h3)", margin: "0 0 8px" }}>
              <Link href={tool.href} style={{ color: "var(--ink-900)", textDecoration: "none" }}>
                {tool.title}
              </Link>
            </h2>
            <p style={{ color: "var(--ink-500)", margin: 0, fontSize: "var(--text-sm)" }}>
              {tool.blurb}
            </p>
          </Card>
        ))}
      </div>

      <p style={{ color: "var(--ink-500)", maxWidth: "62ch", margin: 0 }}>
        Need the other direction — a raster image turned into a vector?{" "}
        <Link href="/convert">That is the converter</Link>, and the preview is free too.
      </p>
    </div>
  );
}

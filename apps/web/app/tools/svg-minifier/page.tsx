import type { Metadata } from "next";
import Link from "next/link";
import SvgMinifier from "@/components/tools/SvgMinifier";
import { Faq } from "@/components/JsonLd";

export const metadata: Metadata = {
  title: "SVG minifier",
  description:
    "Make an SVG smaller in your browser: drop editor metadata, unreferenced ids and excess decimal places, and see the before and after rendered side by side.",
  alternates: { canonical: "/tools/svg-minifier" },
};

const FAQ = [
  {
    question: "Is my file uploaded?",
    answer:
      "No. The minifier runs in your browser — the file is read, rewritten and rendered locally, and nothing is sent to us. You can check by watching the network tab, or by disconnecting entirely: the tool keeps working.",
  },
  {
    question: "Will it change how my SVG looks?",
    answer:
      "It only removes things that cannot affect rendering — comments, editor metadata, empty groups, ids nothing references — plus decimal places you choose. Rounding is the one setting that can matter: at 2 decimals the difference is far below a pixel on any realistic size, at 0 you may see corners move. Both versions are rendered side by side so you can see for yourself.",
  },
  {
    question: "Why is an exported SVG so large in the first place?",
    answer:
      "Drawing apps store their own state in the file: layer names, grid settings, editing history, and coordinates at full floating-point precision. None of it is needed to draw the picture. On a typical Illustrator or Inkscape export that is where most of the size goes.",
  },
  {
    question: "How much smaller should I expect?",
    answer:
      "For an editor export, 30–60% is normal and comes mostly from metadata. For an already-clean file it might be a few percent, and that is the honest answer rather than a headline number.",
  },
];

export default function SvgMinifierPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-7)" }}>
      <div style={{ maxWidth: "62ch", display: "grid", gap: "var(--space-3)" }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>SVG minifier</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Drop or paste an SVG. It is minified in your browser, and both versions are
          rendered below so you can confirm nothing moved.
        </p>
      </div>

      <SvgMinifier />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>What it removes, and what it does not</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Removed: comments, <code>&lt;metadata&gt;</code>, editor-namespace elements and
          attributes, empty groups, ids nothing references, and decimal places beyond the
          precision you set.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Left alone: the root <code>&lt;title&gt;</code> and <code>&lt;desc&gt;</code>,
          which screen readers use; anything referenced by a gradient, clip path, filter or{" "}
          <code>use</code>; and the structure of your document. A minifier that flattens
          groups saves a few more bytes and costs you the ability to edit the file, which
          is a bad trade for artwork you still work on.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          If the file came out of a tracer rather than a drawing app, the bytes are in the
          path data, not the metadata — fewer, better-placed points is the fix, and{" "}
          <Link href="/convert">our converter</Link> optimises for exactly that.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

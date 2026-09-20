import type { Metadata } from "next";
import Link from "next/link";
import PaletteExtractor from "@/components/tools/PaletteExtractor";
import { Faq } from "@/components/JsonLd";

export const metadata: Metadata = {
  title: "Image palette extractor",
  description:
    "Pull the dominant colours out of any image as hex values, with the share of the image each colour covers. Runs in your browser.",
  alternates: { canonical: "/tools/palette-extractor" },
};

const FAQ = [
  {
    question: "How are the colours chosen?",
    answer:
      "By median cut: the colour cube is repeatedly split along whichever axis spans the widest range until there are as many boxes as you asked for, and each box reports its average. Counting the most common pixel values instead sounds simpler and fails on photographs, where almost no exact value repeats.",
  },
  {
    question: "Why do the percentages matter?",
    answer:
      "They tell you which colours are structural and which are incidental. A colour covering 30% of a logo is part of the brand; one covering 0.4% is usually an edge artefact, a shadow or a compression fringe — and it is the kind of thing worth removing before tracing.",
  },
  {
    question: "Will these match my brand's official hex values?",
    answer:
      "Close, not identical. Anti-aliased edges, JPEG compression and screenshots all shift colours slightly, and the average of a region is not the exact value at its centre. Use these as a starting point and paste in the official values where you have them.",
  },
  {
    question: "Does it handle transparency?",
    answer:
      "Transparent pixels are skipped rather than counted as white, which matters for a logo on a transparent background — otherwise white dominates the palette of an image that contains no white at all.",
  },
];

export default function PaletteExtractorPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-7)" }}>
      <div style={{ maxWidth: "62ch", display: "grid", gap: "var(--space-3)" }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Palette extractor</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Drop an image and get its dominant colours as hex, with how much of the image
          each one covers. Nothing is uploaded.
        </p>
      </div>

      <PaletteExtractor />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Using this before you trace</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          The most useful number here is the count. If the palette settles into four
          meaningful colours and then a tail of near-duplicates, that tail is what a
          tracer will faithfully turn into extra shapes — so set the converter&rsquo;s
          colour count to the number of real colours and the result gets simpler and
          closer to the original at the same time.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          It is also a fast sanity check on a file someone has sent you. A “two-colour
          logo” whose palette shows eleven colours has been through a JPEG, and knowing
          that changes what you should expect from it.{" "}
          <Link href="/jpg-to-svg">That page explains why</Link>.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

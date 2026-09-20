import type { Metadata } from "next";
import Converter from "@/components/Converter";
import { Faq, SoftwareApplicationLd } from "@/components/JsonLd";

/**
 * §9 — an intent page, not a doorway. The copy is about the one thing that
 * makes a JPEG different from every other input: it has already been
 * damaged, and tracing amplifies that damage unless you undo it first.
 */

export const metadata: Metadata = {
  title: "JPG to SVG converter",
  description:
    "Convert a JPG or JPEG to a clean SVG. We undo the compression blocking first, so the trace follows the artwork instead of the artefacts.",
  alternates: { canonical: "/jpg-to-svg" },
};

const FAQ = [
  {
    question: "Why do JPGs trace worse than PNGs?",
    answer:
      "Because a JPG has already thrown information away. Compression leaves 8×8 blocks and coloured fringes around edges, and a tracer cannot tell those apart from real detail — so it faithfully traces the damage. We detect the artefacts and clean them before tracing, which is why the same logo gives a very different result here than in a tool that traces the file as-is.",
  },
  {
    question: "My JPG is a photo, not a logo. Will that work?",
    answer:
      "It will produce a vector, but be realistic about what that means: a photograph becomes hundreds of colour regions, and the file gets large. It is the right choice for a poster-style or screen-print look, and the wrong choice if you want the photo to stay a photo. The preview shows you which you are getting before you pay.",
  },
  {
    question: "Should I re-save my JPG as a PNG first?",
    answer:
      "No. Re-saving does not restore anything — the information left when the JPG was written. Upload the JPG you have, and give us the largest version you can find rather than the one already resized for a website.",
  },
  {
    question: "There is a white box around my logo. Can you remove it?",
    answer:
      "Yes. JPG cannot store transparency, so a logo exported to JPG always arrives on a solid background. Tick “Remove background” in the adjust panel and the flat colour behind the artwork is dropped instead of traced as its own shape.",
  },
];

export default function JpgToSvgPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-8)" }}>
      <SoftwareApplicationLd
        name="JPG to SVG converter"
        description="Convert JPG and JPEG images to clean, editable SVG files."
      />
      <div style={{ maxWidth: 620 }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: "0 0 12px" }}>JPG to SVG converter</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Drop a JPG below. We clean up the compression damage first, then trace — so the
          shapes follow your artwork instead of the blocks the compressor left behind.
        </p>
      </div>

      <Converter />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>
          What JPG compression does to a trace
        </h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          JPG works by discarding detail your eye is bad at noticing. On a photograph that
          is a fair trade. On a logo — flat colour, hard edges, sharp corners — it is
          exactly the wrong thing to discard, and the result is two visible failures:
          faint 8×8 squares across areas that should be one flat colour, and coloured
          fringes along every edge.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          A tracer has no way to know those are not real. It sees an edge and draws one.
          That is where the wobbly outlines and the dozens of near-identical colours in
          other converters come from: they are tracing the compression, not the logo.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          We measure the blocking before deciding what to do about it, and we only
          de-artifact files that were actually saved in a lossy format. A clean PNG is
          left alone — over-smoothing a good file costs you the corners you were trying to
          keep.
        </p>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Getting the best out of a JPG</h2>
        <ul
          style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}
        >
          <li>
            <strong>Find the biggest copy.</strong> The version attached to an old email is
            usually larger than the one on the website. Pixels you have beat pixels we
            have to invent.
          </li>
          <li>
            <strong>Avoid screenshots.</strong> A screenshot of a JPG is a JPG of a JPG:
            two rounds of damage, and the second is the one that shows.
          </li>
          <li>
            <strong>Tick “Remove background”</strong> for a logo that arrived on white.
          </li>
          <li>
            <strong>Lower “How many colours?”</strong> if the original was a two- or
            three-colour design. It stops the compression fringes from becoming colour
            regions of their own.
          </li>
        </ul>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

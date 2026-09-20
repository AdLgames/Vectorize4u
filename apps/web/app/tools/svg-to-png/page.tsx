import type { Metadata } from "next";
import Link from "next/link";
import SvgToPng from "@/components/tools/SvgToPng";
import { Faq } from "@/components/JsonLd";

export const metadata: Metadata = {
  title: "SVG to PNG converter",
  description:
    "Rasterise an SVG to PNG at any width, with or without a transparent background. Runs in your browser — nothing is uploaded.",
  alternates: { canonical: "/tools/svg-to-png" },
};

const FAQ = [
  {
    question: "What width should I pick?",
    answer:
      "Match the largest place the image will appear, then stop. For a website logo that is usually twice its display width, to cover high-density screens. For print, work back from the physical size: 300 dpi means about 1180 px for a 100 mm wide image.",
  },
  {
    question: "My text came out in the wrong font.",
    answer:
      "An SVG that uses a web font does not carry that font into a canvas, so the browser substitutes one. Convert the text to outlines in your drawing app before exporting, which is what you should do for print anyway.",
  },
  {
    question: "Why is my PNG blurry when the SVG is sharp?",
    answer:
      "Because a PNG has a fixed number of pixels and an SVG does not. Rasterise at the size you will actually use rather than scaling the PNG up afterwards — scaling up is the blur.",
  },
  {
    question: "Should I be doing this at all?",
    answer:
      "For a favicon, an email signature or a marketplace that rejects vector files, yes. For a website, keep the SVG: it is smaller, sharper at every size, and stays crisp when someone zooms.",
  },
];

export default function SvgToPngPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-7)" }}>
      <div style={{ maxWidth: "62ch", display: "grid", gap: "var(--space-3)" }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>SVG to PNG</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Pick a width, keep or drop the transparency, download the PNG. It is rendered by
          your own browser, so the file never leaves your machine.
        </p>
      </div>

      <SvgToPng />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Transparency, and where it bites</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          A transparent PNG is right for placing a logo over a photo or a coloured panel.
          It is wrong for anywhere that composites badly — some email clients, some print
          workflows, and any process that will flatten it onto white without telling you.
          When in doubt, export the version with a background: a visible white box is a
          problem you can see, and a dark halo from bad compositing is one you often
          cannot until it is printed.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Going the other way — a PNG that needs to become a vector —{" "}
          <Link href="/png-to-svg">starts here</Link>, and the preview costs nothing.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

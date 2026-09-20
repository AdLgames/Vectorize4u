import type { Metadata } from "next";
import Converter from "@/components/Converter";
import { Faq, SoftwareApplicationLd } from "@/components/JsonLd";

/**
 * §9 — ships with the web app in Phase 3, because indexing takes months and
 * that clock has to start early. This is a **working converter**, not a
 * doorway page: thin doorway pages get penalised, and they also convert
 * nobody.
 */

export const metadata: Metadata = {
  title: "PNG to SVG converter",
  description:
    "Convert a PNG to a clean, editable SVG. Free preview, no watermark on the file you buy, and an honest quality score before you pay.",
  alternates: { canonical: "/png-to-svg" },
};

const FAQ = [
  {
    question: "Will my PNG's transparency survive?",
    answer:
      "Yes. Transparent PNGs keep their transparency, and we correct premultiplied alpha, which is what causes dark halos around soft edges in other converters.",
  },
  {
    question: "My PNG is small and blurry. Is that a problem?",
    answer:
      "Small inputs are the single biggest cause of disappointing output. We upscale before tracing, which helps, but detail that isn't in the original can't be invented. We tell you when this applies.",
  },
  {
    question: "Can I edit the SVG in Illustrator or Inkscape?",
    answer:
      "Yes. Shapes are grouped by colour and named, so you can select and recolour a whole layer in one click.",
  },
  {
    question: "Is the preview watermarked?",
    answer:
      "The preview is. The file you download is not. We never send the vector file to your browser before you unlock it.",
  },
];

export default function PngToSvgPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-8)" }}>
      <SoftwareApplicationLd
        name="PNG to SVG converter"
        description="Convert PNG images to clean, editable SVG files."
      />
      <div style={{ maxWidth: 620 }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: "0 0 12px" }}>PNG to SVG converter</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Drop a PNG below. You’ll get a free, zoomable preview of the traced result and a
          quality score before you decide whether to buy it.
        </p>
      </div>

      <Converter />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>What actually happens to your PNG</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          A PNG is a grid of pixels; an SVG is a set of shapes. Converting between them
          means deciding where one colour region ends and the next begins — and there is
          no single right answer, which is why the same file looks good in one tool and
          bad in another.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          We don’t make that decision once. We clean the image, run several traces with
          different settings in parallel, render each result back to pixels, and compare
          them against the cleaned original. The one that matches best — without exploding
          into tens of thousands of points — is what you see.
        </p>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Transparency, and the dark halo</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          PNG is the format people reach for because it keeps transparency, and it is also
          where a specific bug lives. A PNG can store its colours either straight or
          premultiplied by the alpha channel, and the file does not always say which.
          Software that assumes the wrong one darkens every semi-transparent pixel — which
          is why a logo with a soft edge so often arrives with a grey outline nobody asked
          for.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          We detect which kind of alpha a file has rather than assuming, and correct only
          the files that need it. A dark logo that was always meant to be dark is left
          exactly as it was.
        </p>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>When SVG is the wrong answer</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Vector suits flat colour, hard edges and artwork that has to scale: logos, icons,
          line art, anything being cut or engraved. A photograph traced to SVG becomes
          hundreds of colour regions and a file far larger than the PNG you started with,
          and it will not look like a photograph any more.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          If you simply need a smaller or larger PNG, resizing it is the better tool. If you
          need the poster-style look that tracing a photo gives, the preview will show you
          exactly that before you decide — which is the point of previewing first.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

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
    <div className="mx-auto max-w-6xl space-y-12 px-4 py-10">
      <SoftwareApplicationLd
        name="PNG to SVG converter"
        description="Convert PNG images to clean, editable SVG files."
      />
      <div className="space-y-4">
        <h1 className="text-3xl font-semibold tracking-tight">PNG to SVG converter</h1>
        <p className="max-w-2xl text-lg text-slate-600 dark:text-slate-300">
          Drop a PNG below. You’ll get a free, zoomable preview of the traced result and a
          quality score before you decide whether to buy it.
        </p>
      </div>

      <Converter heading="Convert your PNG" />

      <section className="max-w-3xl space-y-4">
        <h2 className="text-xl font-semibold">What actually happens to your PNG</h2>
        <p className="text-slate-600 dark:text-slate-300">
          A PNG is a grid of pixels; an SVG is a set of shapes. Converting between them
          means deciding where one colour region ends and the next begins — and there is
          no single right answer, which is why the same file looks good in one tool and
          bad in another.
        </p>
        <p className="text-slate-600 dark:text-slate-300">
          We don’t make that decision once. We clean the image, run several traces with
          different settings in parallel, render each result back to pixels, and compare
          them against the cleaned original. The one that matches best — without exploding
          into tens of thousands of points — is what you see.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

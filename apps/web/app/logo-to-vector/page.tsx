import type { Metadata } from "next";
import Converter from "@/components/Converter";
import { Faq, SoftwareApplicationLd } from "@/components/JsonLd";

/**
 * §9 — the intent here is not a file conversion, it is a rescue: someone has
 * inherited a logo as a small raster and needs something they can print
 * large and edit. The copy is about what can and cannot be recovered, which
 * is also the honest answer (§0).
 */

export const metadata: Metadata = {
  title: "Logo to vector converter",
  description:
    "Turn a raster logo into an editable vector you can scale, recolour and print at any size — with an honest quality score before you pay.",
  alternates: { canonical: "/logo-to-vector" },
};

const FAQ = [
  {
    question: "The only copy of our logo is a small PNG from the website. Is that enough?",
    answer:
      "Usually yes for print at moderate sizes, and the preview will tell you. We upscale before tracing, which recovers edges convincingly, but detail that was never captured cannot be invented — a 200px logo with small text under it will trace the shape of the text rather than the letters. We say so in the warnings instead of letting you find out at the printer.",
  },
  {
    question: "Will the colours match our brand exactly?",
    answer:
      "The trace uses the colours in your file, merged where they are visually identical, so you get a small clean palette rather than forty near-duplicates. If you have brand hex values, set the colour count to the number of brand colours and then correct the few swatches by hand in Illustrator or Inkscape — that takes a minute and is exact, which guessing never is.",
  },
  {
    question: "Can I edit the result, or is it one flat shape?",
    answer:
      "It is editable. Shapes are grouped by colour and named, so selecting every red part and changing it is one click. Stacking order is preserved, which is what keeps a logo with an outline or a drop shape looking right after you edit it.",
  },
  {
    question: "What about the typeface in our logo?",
    answer:
      "A trace gives you outlines of the letters, not live text — nobody can recover a font from pixels. Outlines are what a printer wants anyway. If you need to edit the wording, identify the typeface and set it fresh; the traced outlines are a good reference for matching the weight and spacing.",
  },
  {
    question: "Do you keep our logo?",
    answer:
      "Only for the retention window of your plan, and you can purge it immediately from the job. We keep statistics about the trace — how many nodes, how well it scored — because that is what improves the engine. We do not keep the pixels beyond that window.",
  },
];

export default function LogoToVectorPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-8)" }}>
      <SoftwareApplicationLd
        name="Logo to vector converter"
        description="Convert a raster logo into an editable, scalable vector file."
      />
      <div style={{ maxWidth: 620 }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: "0 0 12px" }}>Logo to vector</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          The usual situation: the only copy of the logo is a small image someone pulled
          off the website, and now it needs to go on a sign. Drop it below and see what
          comes back before you spend anything.
        </p>
      </div>

      {/* Logos are flat-colour work: a small palette and clean edges matter
          more than texture, so the colour cap starts low. */}
      <Converter defaultOptions={{ max_colors: 8, despeckle: 6 }} />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>What you get back</h2>
        <ul
          style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}
        >
          <li>
            <strong>An SVG that scales.</strong> The same file works on a business card
            and on a vehicle wrap, because there are no pixels left to run out of.
          </li>
          <li>
            <strong>A small, named palette.</strong> Near-identical colours are merged and
            grouped, so recolouring is selecting a group rather than shift-clicking
            forty shapes.
          </li>
          <li>
            <strong>PDF and EPS</strong> for printers who ask for them, and DXF if the
            logo is going to be cut or engraved.
          </li>
          <li>
            <strong>A score, and warnings.</strong> If the source was too small or too
            compressed to give a good result, that is on the screen before you pay.
          </li>
        </ul>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>
          What a trace can and cannot recover
        </h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Tracing recovers <em>shape</em>. Hard edges, flat colour areas, curves and
          corners all come back cleanly, and usually look better than the original
          because the staircase edges of a small raster disappear.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          It cannot recover <em>information that was never there</em>. Small type, hairline
          rules, fine gradients and soft shadows were approximated by a handful of pixels,
          and no amount of cleverness turns those pixels back into the original artwork.
          A converter that claims otherwise is guessing, and guessing on a logo is how you
          end up with a sign that is subtly wrong at three metres.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          So: if the original vector exists anywhere — the agency that made it, an old
          invoice PDF, the print file from the last run of business cards — that is worth
          ten minutes of looking first. If it does not, this is the next best thing, and
          the preview tells you honestly how close it got.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

import type { Metadata } from "next";
import Converter from "@/components/Converter";
import { Faq, SoftwareApplicationLd } from "@/components/JsonLd";
import { Notice } from "@/components/ui";

/**
 * §9 is explicit about this page: it says plainly that we produce clean art
 * for Ink/Stitch, Hatch and similar, **not stitch files**. Ranking for
 * "embroidery digitizing" and then selling someone an SVG they thought was
 * a .dst is a refund and a bad review, so the disclaimer is above the
 * converter rather than in the small print.
 */

export const metadata: Metadata = {
  title: "Vector art for embroidery digitizing",
  description:
    "Turn a logo into clean, closed-path vector art ready to digitize in Ink/Stitch, Hatch or Wilcom. We produce the artwork, not the stitch file.",
  alternates: { canonical: "/vector-art-for-embroidery-digitizing" },
};

const FAQ = [
  {
    question: "Do you produce DST, PES or EXP files?",
    answer:
      "No. Those are stitch files — they contain needle positions, stitch types, densities, underlay and trims, and they are made in digitizing software by a person who knows the fabric, the hoop and the machine. We produce the vector artwork that goes into that software. Anyone selling you an automatic image-to-DST conversion is selling you something that will look wrong on the garment.",
  },
  {
    question: "So what do I actually get?",
    answer:
      "An SVG with closed paths, a small flat palette, one shape per colour area and preserved stacking order — which is exactly the input Ink/Stitch, Hatch, Wilcom and Embrilliance want. You import it, assign stitch types and run your own underlay and pull-compensation settings.",
  },
  {
    question: "How many colours should I ask for?",
    answer:
      "Match the thread count you intend to use, and set the colour slider to that number. Embroidery is expensive per colour change, and a trace that returns eighteen near-identical shades gives you eighteen problems to merge by hand. Four to six is typical for a logo.",
  },
  {
    question: "How small can the details be?",
    answer:
      "Smaller than about 1.5 mm of finished detail does not survive being stitched — thin lines close up, small text turns into a blob, and tiny islands pull out. Set the finished width first, then look at the preview at that size: what you cannot read there, you will not read on a shirt. Simplify the artwork rather than hoping the digitizer can save it.",
  },
  {
    question: "Can you handle gradients and photographs?",
    answer:
      "You can convert them, but you should not want to. Embroidery is flat colour areas with hard boundaries; a gradient traced into forty bands becomes forty thread changes. Cap the colours, or redraw the gradient as two or three flat steps before you trace.",
  },
];

export default function EmbroideryArtPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-8)" }}>
      <SoftwareApplicationLd
        name="Vector art for embroidery digitizing"
        description="Convert logos into clean closed-path vector art for embroidery digitizing software."
      />
      <div style={{ maxWidth: 620 }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: "0 0 12px" }}>
          Vector art for embroidery digitizing
        </h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Clean, closed-path artwork with a small flat palette — the file your digitizing
          software wants to start from, instead of a screenshot of a logo.
        </p>
      </div>

      <div style={{ maxWidth: "68ch" }}>
        <Notice tone="amber" title="We make the artwork, not the stitch file">
          You get an SVG (and PDF, EPS or DXF) to import into Ink/Stitch, Hatch, Wilcom or
          Embrilliance. You do not get a DST, PES, EXP or JEF. Stitch files are made by a
          digitizer who knows your fabric, hoop and machine, and no automatic conversion
          replaces that.
        </Notice>
      </div>

      {/* Thread counts are small and stitches cannot hold fine specks, so the
          palette starts tight and despeckling starts high. */}
      <Converter defaultOptions={{ max_colors: 6, despeckle: 8, keep_background: false }} />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>
          What makes artwork easy to digitize
        </h2>
        <ul
          style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}
        >
          <li>
            <strong>Closed paths.</strong> A fill needs a boundary. Open paths and hairline
            strokes are the most common reason a digitizer sends artwork back.
          </li>
          <li>
            <strong>One shape per colour area,</strong> grouped by colour, so assigning a
            stitch type to “all the red” is one selection.
          </li>
          <li>
            <strong>Stacking order preserved.</strong> Embroidery is literally layered —
            what sits on top here sits on top on the garment.
          </li>
          <li>
            <strong>No specks or slivers.</strong> Anything smaller than a stitch is either
            skipped or becomes a knot on the back.
          </li>
          <li>
            <strong>A real physical size.</strong> Set the finished width in the panel and
            judge the detail at that size, not at screen size.
          </li>
        </ul>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>A workable order of operations</h2>
        <ol
          style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}
        >
          <li>Trace here with the colour count set to your thread count.</li>
          <li>Set the finished width — left chest is usually 75–90 mm, a cap front 50–60 mm.</li>
          <li>
            Look at the preview at that width and delete or simplify anything under about
            1.5&nbsp;mm.
          </li>
          <li>Import the SVG into your digitizing software and assign stitch types.</li>
          <li>Run underlay and pull compensation, then sew a test on the actual fabric.</li>
        </ol>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Step five is not optional. Fabric stretches, and the only honest test of an
          embroidery file is a sample on the material it will be sewn on.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

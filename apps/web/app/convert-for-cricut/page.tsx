import type { Metadata } from "next";
import Converter from "@/components/Converter";
import { Faq, SoftwareApplicationLd } from "@/components/JsonLd";

/**
 * A cut-intent page (§3.8): it asks "How wide should this be?" before
 * anything is downloaded, because a confidently wrong physical size is the
 * one failure a cutter user cannot recover from.
 */

export const metadata: Metadata = {
  title: "Convert an image for Cricut",
  description:
    "Turn a PNG or JPEG into an SVG that opens at the right size in Cricut Design Space, with paths a blade can actually follow.",
  alternates: { canonical: "/convert-for-cricut" },
};

const FAQ = [
  {
    question: "Why does my SVG import at the wrong size in Design Space?",
    answer:
      "Because most converters write an SVG with no physical size at all, and cutting software then guesses. We write explicit millimetres or inches alongside the viewBox, so the size you ask for here is the size it opens at.",
  },
  {
    question: "What does 'cutter-safe paths' mean?",
    answer:
      "Two things. We enforce a minimum distance between points — dense clusters make a blade tear vinyl and confuse laser controllers — and we drop stray specks that would otherwise become tiny unwanted cuts.",
  },
  {
    question: "Should I use SVG or DXF for my machine?",
    answer:
      "Cricut Design Space takes SVG. Most laser software (LightBurn, for example) is happier with DXF, which we write with absolute units and curves flattened to polylines. Both are included.",
  },
  {
    question: "Can I cut a photograph?",
    answer:
      "Realistically, no. A photo traces into thousands of overlapping colour patches. We'll tell you when an image is a photo rather than let you find out at the machine.",
  },
];

export default function CricutPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-8)" }}>
      <SoftwareApplicationLd
        name="Image to Cricut SVG converter"
        description="Convert images to cut-ready SVG and DXF at a specified physical size."
      />
      <div style={{ maxWidth: 620 }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: "0 0 12px" }}>
          Convert an image for Cricut
        </h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Cut files fail for boring reasons: the wrong scale, paths with too many points,
          specks that become stray cuts. Tell us how wide the finished piece should be and
          we’ll handle the rest.
        </p>
      </div>

      {/* cutIntent makes the width question mandatory, and DXF is on by
          default because it is why cutter users show up (§10). */}
      <Converter cutIntent defaultFormats={["svg", "dxf"]} />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Before you press cut</h2>
        <ol style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}>
          <li>
            Set the width above. Measure the finished piece, not the screen.
          </li>
          <li>
            Import the SVG into Design Space and check the size reads back correctly. It
            should match to within a rounding error.
          </li>
          <li>
            Look at the smallest details at 400% zoom in the preview. If a thin line has
            broken up, lower the Detail setting — thin strokes cut badly anyway.
          </li>
          <li>
            Do a test cut on scrap for anything under about 5&nbsp;mm.
          </li>
        </ol>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Inside Design Space</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          An imported SVG arrives as a group, one layer per colour. Ungroup it to cut each
          colour from its own material, or attach the layers to keep them in position
          relative to one another — attaching is what stops Design Space rearranging your
          artwork onto the mat as separate pieces.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          For heat transfer vinyl, remember to mirror the design before cutting and to cut
          the material face down. Nothing in the file can do that for you, and it is the
          most common reason a perfectly good cut ends up backwards on the shirt.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          For Print Then Cut, the artwork is printed and the cut line follows the outside
          of the shapes, so a design with a lot of tiny separate islands is worth
          simplifying first — every island is another registration-sensitive cut.
        </p>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Material decides the detail</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          The same file cuts beautifully in cardstock and tears in vinyl. Thin material and
          weeding favour simple shapes: raise “Clean up specks” and lower the detail, and
          the design will weed in a minute rather than half an hour under a magnifier.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Chipboard and thick leather are the other direction — the blade needs room to
          turn, so very tight corners and narrow necks between shapes will round off
          regardless of what the file says. Design for the material you have, then check
          the preview at the finished size rather than at screen size.
        </p>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

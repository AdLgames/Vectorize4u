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
    <div className="mx-auto max-w-6xl space-y-12 px-4 py-10">
      <SoftwareApplicationLd
        name="Image to Cricut SVG converter"
        description="Convert images to cut-ready SVG and DXF at a specified physical size."
      />
      <div className="space-y-4">
        <h1 className="text-3xl font-semibold tracking-tight">
          Convert an image for Cricut
        </h1>
        <p className="max-w-2xl text-lg text-slate-600 dark:text-slate-300">
          Cut files fail for boring reasons: the wrong scale, paths with too many points,
          specks that become stray cuts. Tell us how wide the finished piece should be and
          we’ll handle the rest.
        </p>
      </div>

      {/* cutIntent makes the width question mandatory, and DXF is on by
          default because it is why cutter users show up (§10). */}
      <Converter
        heading="Upload your design"
        cutIntent
        defaultFormats={["svg", "dxf"]}
      />

      <section className="max-w-3xl space-y-4">
        <h2 className="text-xl font-semibold">Before you press cut</h2>
        <ol className="list-decimal space-y-2 pl-5 text-slate-600 dark:text-slate-300">
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

      <Faq items={FAQ} />
    </div>
  );
}

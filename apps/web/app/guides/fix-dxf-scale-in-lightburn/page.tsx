import type { Metadata } from "next";
import Link from "next/link";
import { ArticleLd, Faq } from "@/components/JsonLd";
import { Bullets, GuideHeader, GuideLayout, P, Section, Steps } from "@/components/guides/Prose";

export const metadata: Metadata = {
  title: "Fix DXF scale in LightBurn",
  description:
    "Why a DXF imports at 25.4× the size you expected, how to correct it in LightBurn in under a minute, and how to make the next file arrive at the right size.",
  alternates: { canonical: "/guides/fix-dxf-scale-in-lightburn" },
};

const FAQ = [
  {
    question: "Why 25.4?",
    answer:
      "There are 25.4 millimetres in an inch. A file whose numbers mean inches, read as millimetres, comes in 25.4 times too small; the same file read the other way is 25.4 times too big. If your wrong size divides or multiplies neatly by 25.4, units are the cause and nothing else needs investigating.",
  },
  {
    question: "Can I just scale it and move on?",
    answer:
      "For one file, yes — set the width numerically and cut. For a file you will use repeatedly, fix the export: manual scaling is a step you will eventually forget, and forgetting it on a sheet of expensive material is an expensive lesson.",
  },
  {
    question: "Does this apply to SVG too?",
    answer:
      "Yes, with a different mechanism. An SVG that declares only a viewBox and no width and height in real units leaves the importing app to guess, and different apps guess differently — which is why the same SVG opens at one size in LightBurn and another in Design Space.",
  },
];

export default function LightburnGuide() {
  return (
    <GuideLayout>
      <ArticleLd
        headline="Fix DXF scale in LightBurn"
        description="Diagnosing and correcting a DXF that imports at the wrong size, and preventing it at export."
        slug="/guides/fix-dxf-scale-in-lightburn"
        published="2026-09-20"
      />
      <GuideHeader
        title="Fix DXF scale in LightBurn"
        standfirst="Your 100 mm design arrives 3.9 mm wide, or 2540 mm wide. It is almost never LightBurn's fault, and the fix takes under a minute once you know which of two things happened."
        minutes={6}
      />

      <Section title="Diagnose it in ten seconds">
        <P>
          Select everything after import and read the width in the toolbar. Divide what you
          expected by what you got:
        </P>
        <Bullets>
          <li>
            <strong>25.4 or 1/25.4</strong> — a units mismatch. The file&rsquo;s numbers mean
            inches and are being read as millimetres, or the reverse.
          </li>
          <li>
            <strong>Some other number</strong> — the file was drawn at an arbitrary scale,
            or exported from pixels with no physical size at all. A 1000-pixel-wide design
            landing as 1000 mm is this case, not a units mismatch.
          </li>
        </Bullets>
        <P>
          The distinction matters because the first is a property of the file&rsquo;s header
          and the second is a property of how the file was made — and only one of them can
          be fixed at the source by whoever exported it.
        </P>
      </Section>

      <Section title="Fix this file now">
        <Steps>
          <li>Select all (Ctrl+A).</li>
          <li>
            In the toolbar, type the correct width into the W field with the lock icon
            engaged so height follows. Never drag a corner: dragging is an approximation
            and this needs to be exact.
          </li>
          <li>
            Check a known feature. If the design contains a 10 mm circle or a hole for an
            M4 screw, measure that rather than trusting the overall width — overall width
            includes any stray geometry that came in with the file.
          </li>
          <li>Set the origin, then cut a test on scrap.</li>
        </Steps>
        <P>
          If you find stray geometry while doing this — a stray point far from the artwork
          inflating the bounding box — delete it before scaling, or your correct width will
          be correct for the wrong bounding box.
        </P>
      </Section>

      <Section title="Fix the next file">
        <P>
          A DXF stores coordinates and one header variable, <code>$INSUNITS</code>, that
          says what those coordinates mean: 1 for inches, 4 for millimetres. Plenty of
          converters never write it. LightBurn then applies its own default, and you get
          the 25.4.
        </P>
        <P>
          So the durable fix is at export. Whatever tool produces your DXF should let you
          state a physical size, and should write the units into the file. Ours asks for
          the finished width before it will let you download, writes{" "}
          <code>$INSUNITS</code> to match, and flips the Y axis so the result is not
          mirrored — see <Link href="/image-to-dxf">image to DXF</Link> for the detail.
        </P>
        <P>
          If you are stuck with a source that cannot declare units, standardise: always
          export in millimetres, and put the intended width in the filename
          (<code>bracket-120mm.dxf</code>). It is a crude fix that works, because the person
          who gets burned by the wrong scale is usually the person who exported it three
          weeks earlier.
        </P>
      </Section>

      <Section title="While you are in there">
        <Bullets>
          <li>
            <strong>Check for doubled lines.</strong> Many converters emit each cut line
            twice; the laser will cut it twice, which burns wide edges and doubles the job
            time. LightBurn&rsquo;s &ldquo;Delete duplicates&rdquo; handles it.
          </li>
          <li>
            <strong>Check node density.</strong> Hundreds of nodes in a centimetre of curve
            makes the controller stutter and leaves visible facets. If the file came from a
            trace, re-export it with a wider minimum node spacing rather than fighting it
            here.
          </li>
          <li>
            <strong>Check the layers.</strong> Colours become layers in a DXF, which is
            exactly what you want for assigning different power and speed per material —
            worth setting up before the first cut rather than after.
          </li>
        </Bullets>
      </Section>

      <Faq items={FAQ} />
    </GuideLayout>
  );
}

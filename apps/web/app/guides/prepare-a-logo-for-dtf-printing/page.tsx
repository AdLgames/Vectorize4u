import type { Metadata } from "next";
import Link from "next/link";
import { ArticleLd, Faq } from "@/components/JsonLd";
import { Bullets, GuideHeader, GuideLayout, P, Section, Steps } from "@/components/guides/Prose";

export const metadata: Metadata = {
  title: "Prepare a logo for DTF printing",
  description:
    "What a DTF printer needs from your artwork: transparency handled correctly, no white box, edges that survive the powder, and a file at the size you are actually printing.",
  alternates: { canonical: "/guides/prepare-a-logo-for-dtf-printing" },
};

const FAQ = [
  {
    question: "Does DTF need a vector file?",
    answer:
      "Not strictly — DTF prints raster, so a large clean PNG works. Vector matters because it gives you a clean PNG at any size: you set the print width and export exactly the pixels you need, instead of stretching whatever the customer sent.",
  },
  {
    question: "How many DPI should the file be?",
    answer:
      "300 dpi at the finished print size is the standard target, so a 250 mm wide print wants about 2950 px. Going higher rarely shows on fabric; going lower shows immediately on small text and thin outlines.",
  },
  {
    question: "Why does my print have a faint outline around the artwork?",
    answer:
      "Almost always premultiplied alpha misread as straight alpha, which darkens semi-transparent edge pixels. It looks like a subtle dark halo on screen and prints as a visible fringe because the white underbase follows those pixels too.",
  },
];

export default function DtfGuide() {
  return (
    <GuideLayout>
      <ArticleLd
        headline="Prepare a logo for DTF printing"
        description="Getting artwork ready for direct-to-film printing: transparency, edges, size and colour."
        slug="/guides/prepare-a-logo-for-dtf-printing"
        published="2026-09-20"
      />
      <GuideHeader
        title="Prepare a logo for DTF printing"
        standfirst="Direct-to-film is forgiving about colour and unforgiving about edges. Most reprints come from four specific problems in the file, and all four are fixable before you press anything."
        minutes={7}
      />

      <Section title="What DTF actually does with your file">
        <P>
          A DTF printer lays down colour, then a white underbase behind it, then powdered
          adhesive that sticks to wet ink. The underbase is generated from your artwork&rsquo;s
          alpha channel — so every decision about transparency in the file becomes a
          physical decision about where white powder lands.
        </P>
        <P>
          That is why DTF punishes things that look harmless on screen. A soft drop shadow
          becomes a halo of adhesive. A 40%-opacity grey becomes a patchy grey over white.
          An anti-aliased edge over the wrong background becomes a dark fringe you cannot
          weed away.
        </P>
      </Section>

      <Section title="The four problems, in the order they bite">
        <Steps>
          <li>
            <strong>A white box.</strong> The artwork arrived as a JPEG, which cannot store
            transparency, so the logo sits on white. Printed, that white is a rectangle of
            ink and underbase. Removing the background properly means removing the
            background <em>region</em>, not just making white pixels transparent — the
            second approach eats the white inside letters like O and A.
          </li>
          <li>
            <strong>A dark halo.</strong> Semi-transparent edge pixels stored premultiplied
            and read as straight. If your printer&rsquo;s RIP shows a grey outline around a
            clean logo, this is it, and fixing it in the file is the only fix.
          </li>
          <li>
            <strong>Soft edges and gradients.</strong> DTF resolves a hard edge beautifully
            and a 5% gradient step not at all. Anything below roughly 10% opacity tends to
            print as nothing, which turns a soft shadow into a hard-edged smudge where it
            crosses that threshold.
          </li>
          <li>
            <strong>The wrong size.</strong> An image scaled up in the RIP at print time is
            the most common cause of ragged type. Export at the finished print size at 300
            dpi and the RIP has nothing to invent.
          </li>
        </Steps>
      </Section>

      <Section title="A workflow that avoids all four">
        <Steps>
          <li>
            Start from the largest version of the artwork you can get. Ask for the original
            vector first; it takes one email and saves the rest of this.
          </li>
          <li>
            If there is no vector, <Link href="/logo-to-vector">trace it</Link>. Set the
            colour count to the number of real colours in the design — the{" "}
            <Link href="/tools/palette-extractor">palette extractor</Link> will tell you
            what that number is.
          </li>
          <li>
            Tick &ldquo;Remove background&rdquo; so the background region goes and the
            counters inside letters stay.
          </li>
          <li>
            Set the output width to your finished print width in millimetres. Download the
            SVG, and the PNG rendered from it if your RIP prefers raster.
          </li>
          <li>
            Check the result at 100% of print size before you print. Anything you cannot
            read there will not appear on fabric.
          </li>
        </Steps>
      </Section>

      <Section title="Minimum sizes worth knowing">
        <Bullets>
          <li>
            <strong>Lines:</strong> below about 0.5 mm they print inconsistently — some
            passes catch powder, some do not.
          </li>
          <li>
            <strong>Text:</strong> around 4 mm cap height is the practical floor for
            anything with fine serifs; a bold sans survives a little smaller.
          </li>
          <li>
            <strong>Gaps:</strong> two shapes closer than roughly 0.5 mm will bridge once
            the adhesive spreads under heat.
          </li>
        </Bullets>
        <P>
          These are all consequences of powder and pressure, not of your file — which is
          precisely why they have to be decided in the file, at the size you are printing.
        </P>
      </Section>

      <Faq items={FAQ} />
    </GuideLayout>
  );
}

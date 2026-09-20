import type { Metadata } from "next";
import Link from "next/link";
import { ArticleLd, Faq } from "@/components/JsonLd";
import { Bullets, GuideHeader, GuideLayout, P, Section, Steps } from "@/components/guides/Prose";

export const metadata: Metadata = {
  title: "Clean up a customer's low-res logo",
  description:
    "A practical routine for the 200-pixel logo a customer swears is the only copy: what to ask for first, what a trace can recover, and when to redraw instead.",
  alternates: { canonical: "/guides/clean-up-a-low-res-logo" },
};

const FAQ = [
  {
    question: "How small is too small?",
    answer:
      "There is no single number, because it depends on what is in the image. A bold wordmark at 300 px across traces well. The same 300 px containing a tagline in 8-pixel-tall type does not, because those letters are five pixels of information each. Judge the smallest feature, not the overall size.",
  },
  {
    question: "Does upscaling with AI help before tracing?",
    answer:
      "Sometimes, and it comes with a specific risk: an upscaler invents plausible detail. On a photo that is fine. On a logo it can alter letterforms and corner radii in ways the client will notice and you will be blamed for. If you use one, compare the result against the original at high zoom before you trace it.",
  },
  {
    question: "What do I charge for this?",
    answer:
      "Price the judgement, not the click. A trace takes a minute; deciding which version is right, fixing the two shapes that came out wrong and matching the brand colours is the work — and it is worth more to the customer than the conversion itself.",
  },
];

export default function LowResGuide() {
  return (
    <GuideLayout>
      <ArticleLd
        headline="Clean up a customer's low-res logo"
        description="A routine for rescuing a small, compressed logo: what to ask for, what to trace, and when to redraw."
        slug="/guides/clean-up-a-low-res-logo"
        published="2026-09-20"
      />
      <GuideHeader
        title="Clean up a customer's low-res logo"
        standfirst="Every print shop has this job: the customer sends a 240-pixel logo lifted from a social profile and needs it on a banner by Thursday. Here is the order of operations that gets the best available answer fastest."
        minutes={8}
      />

      <Section title="Step zero: ask, once, properly">
        <P>
          Before any software, send one email — and be specific, because &ldquo;do you have
          a better version?&rdquo; reliably gets &ldquo;no&rdquo; from people who do. Ask:
          who made the logo, is there an invoice from a designer, is there a PDF of old
          business cards, does the sign company that did the shopfront still have the
          artwork?
        </P>
        <P>
          A PDF of a business card is the jackpot: PDFs usually carry the vector artwork
          intact, and you can pull it out in Illustrator or Inkscape in seconds. This one
          question resolves maybe a third of these jobs and costs two minutes.
        </P>
      </Section>

      <Section title="Judge the file before you process it">
        <P>
          Open it at 400% and look at the smallest thing that has to survive — usually a
          tagline, a registered-trademark symbol, or the thinnest stroke in the mark. That
          feature decides the job, not the pixel dimensions in the file&rsquo;s properties.
        </P>
        <P>
          Then check how much damage the file already carries. Run it through the{" "}
          <Link href="/tools/palette-extractor">palette extractor</Link>: a two-colour logo
          that reports eleven colours has been through JPEG compression, and those extra
          colours are fringes that a tracer will otherwise turn into real shapes.
        </P>
      </Section>

      <Section title="The routine">
        <Steps>
          <li>
            Trace it with the colour count set to the number of real brand colours, not the
            number the file contains.
          </li>
          <li>
            Turn despeckling up. On a compressed source, small specks are almost always
            artefacts rather than design.
          </li>
          <li>
            Look at the preview at the finished size — a banner at 2 m is judged at 2 m,
            not at 100% on your monitor.
          </li>
          <li>
            Fix the two or three shapes that came out wrong by hand. There are almost
            always two or three: a counter that filled in, a corner that rounded, a serif
            that merged. Five minutes in Illustrator finishes the job properly.
          </li>
          <li>
            Replace the traced colours with the brand&rsquo;s official hex or Pantone values
            where you have them. Traced colours are close, not exact, and &ldquo;close&rdquo;
            is what gets a reprint on a brand with a strong colour.
          </li>
        </Steps>
      </Section>

      <Section title="When to redraw instead">
        <P>
          Tracing recovers shape. If the shape is not in the pixels, no tool recovers it,
          and the honest call is to redraw. Redraw when:
        </P>
        <Bullets>
          <li>The type is small enough that letters are merging into each other.</li>
          <li>
            The logo is geometric — circles, even spacing, consistent stroke weight. A
            trace of a geometric mark is subtly wobbly and looks wrong next to a real one.
          </li>
          <li>
            You can identify the typeface. Setting the wordmark fresh in the right font
            takes ten minutes and gives a better result than any trace.
          </li>
          <li>The output is large and permanent — vehicle livery, signage, etched glass.</li>
        </Bullets>
        <P>
          For everything else — a decent-sized flat logo going onto a shirt, a mug, a
          sticker sheet — a good trace is genuinely the right answer, and{" "}
          <Link href="/logo-to-vector">it takes a minute</Link>.
        </P>
      </Section>

      <Section title="What to tell the customer">
        <P>
          Say what you did and what the limits are, in one sentence: &ldquo;We rebuilt this
          from the small file you had; the mark is clean, and the tagline was too small in
          the original to reproduce exactly, so we reset it in a matching typeface.&rdquo;
        </P>
        <P>
          Customers accept limits explained before the job far better than after it. It is
          also the same reason our converter shows you a score and its warnings before you
          pay rather than after.
        </P>
      </Section>

      <Faq items={FAQ} />
    </GuideLayout>
  );
}

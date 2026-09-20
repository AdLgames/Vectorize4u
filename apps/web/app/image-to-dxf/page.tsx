import type { Metadata } from "next";
import Converter from "@/components/Converter";
import { Faq, SoftwareApplicationLd } from "@/components/JsonLd";

/**
 * §9 — the DXF intent page. Everything here is about units, because a DXF
 * that opens at the wrong size is the one failure a laser or plotter user
 * cannot recover from (§3.8), and it is the failure every other converter
 * ships with.
 */

export const metadata: Metadata = {
  title: "Image to DXF converter",
  description:
    "Convert a PNG or JPG to a DXF that opens at the size you asked for in LightBurn, Fusion, AutoCAD and cutting software — with the drawing units written into the file.",
  alternates: { canonical: "/image-to-dxf" },
};

const FAQ = [
  {
    question: "Why does my DXF open at the wrong size?",
    answer:
      "Because most DXF files do not say what their numbers mean. A DXF stores coordinates; the header variable $INSUNITS says whether a coordinate of 100 means 100 millimetres, 100 inches or 100 of nothing. Converters that leave it unset hand the decision to your software, which guesses — and inches-instead-of-millimetres is a factor of 25.4. We write $INSUNITS to match the units you pick, so there is nothing left to guess.",
  },
  {
    question: "Is my artwork upside down?",
    answer:
      "It should not be. Images count rows downward from the top; CAD counts Y upward from the bottom. Skipping that flip mirrors the drawing, which is easy to miss on a symmetrical shape and obvious once it is engraved. We flip Y on export and check it with an asymmetric test shape.",
  },
  {
    question: "What is the tolerance setting for?",
    answer:
      "DXF has no Bézier curves in the form most cutting software reads reliably, so curves are approximated by short straight segments. The tolerance is how far a segment may sit from the true curve — 0.1 mm is invisible in a cut and keeps the file small. Tighten it for jewellery-scale work; loosen it if your controller stutters on dense geometry.",
  },
  {
    question: "Does DXF keep my colours?",
    answer:
      "No, and it is not meant to. A DXF is geometry: outlines, not fills. Colours become layers, which is what a laser wants — one layer per material or power setting. Download the SVG alongside if you need the artwork itself; the same credit covers every format of one image.",
  },
  {
    question: "Will it work in LightBurn, Fusion 360 and AutoCAD?",
    answer:
      "Yes. We write an R2010 DXF with plain polyline geometry — the dialect everything reads — rather than anything exotic. LightBurn and Fusion both honour $INSUNITS on import; AutoCAD will ask if its drawing units differ from the file's, and the answer is to insert at the file's units.",
  },
];

export default function ImageToDxfPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-8)" }}>
      <SoftwareApplicationLd
        name="Image to DXF converter"
        description="Convert raster images to DXF files with correct drawing units for CAD and laser software."
      />
      <div style={{ maxWidth: 620 }}>
        <h1 style={{ fontSize: "var(--text-h1)", margin: "0 0 12px" }}>Image to DXF</h1>
        <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
          Tell us how wide the finished piece should be, in millimetres or inches. The DXF
          you get back carries that size inside the file, so it opens at the right scale
          instead of whatever your software assumes.
        </p>
      </div>

      {/* cutIntent makes the size question mandatory before download: a
          confidently wrong physical size is unrecoverable (§3.8). */}
      <Converter cutIntent defaultFormats={["svg", "dxf"]} />

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>The scale problem, in one line</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          A DXF is a list of coordinates with no inherent unit. If the file does not
          declare one, your software picks — and a drawing meant to be 100&nbsp;mm wide
          opens 2540&nbsp;mm wide, or 3.9&nbsp;mm wide, depending on which way the guess
          goes. That is the whole story behind “my SVG imported at the wrong size”, and it
          is a one-line fix that most converters never made.
        </p>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          We ask for the width because we would rather ask than guess. The SVG we produce
          alongside carries the same physical size in its width and height attributes, so
          both files agree.
        </p>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Cutting-safe geometry</h2>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          Correct size is necessary and not sufficient. Two more things decide whether a
          file cuts well:
        </p>
        <ul
          style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}
        >
          <li>
            <strong>Point spacing.</strong> A trace can put hundreds of points into a
            centimetre of curve. Blades tear vinyl on dense clusters and laser controllers
            stutter, so we enforce a minimum distance between points — measured in
            millimetres of the finished piece, which is the only measure that means
            anything here.
          </li>
          <li>
            <strong>Specks.</strong> A speck in a photo is invisible; a speck in a cut file
            is a stray cut, or a piece of scrap the machine tries to weed. “Clean up
            specks” drops them before they reach the file.
          </li>
        </ul>
        <p style={{ color: "var(--ink-500)", margin: 0 }}>
          At small finished sizes both settings matter more, not less: a 0.2&nbsp;mm
          feature that looks fine on screen is thinner than the kerf of the tool that has
          to cut it.
        </p>
      </section>

      <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>Check it in 30 seconds</h2>
        <ol
          style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}
        >
          <li>Import the DXF and read the width back. It should match what you typed.</li>
          <li>
            Check an asymmetric part of the artwork — a letter F, a logo mark — is not
            mirrored.
          </li>
          <li>Zoom to the smallest feature and confirm it is still a feature.</li>
          <li>Run the job on scrap before running it on the good material.</li>
        </ol>
      </section>

      <Faq items={FAQ} />
    </div>
  );
}

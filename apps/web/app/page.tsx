import Converter from "@/components/Converter";
import Pricing from "@/components/Pricing";
import { SoftwareApplicationLd } from "@/components/JsonLd";

/**
 * The landing page states §0's positioning without saying it out loud: we
 * are not selling "an SVG converter" — vtracer is free and Illustrator has
 * Image Trace. We sell batch, cut-correctness and honesty about quality.
 *
 * The hero is the converter itself. The zoom is the pitch: the original
 * pixelates, the vector stays sharp.
 */

export default function Home() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-8)" }}>
      <SoftwareApplicationLd
        name="Vectorize4u"
        description="Batch raster-to-vector conversion with cutter-safe output and an exposed quality score."
      />

      <section style={{ display: "grid", gap: "var(--space-5)" }}>
        <div style={{ maxWidth: 620 }}>
          <h1 style={{ fontSize: "var(--text-h1)", margin: "0 0 12px" }}>
            Turn a rough image into a file that prints and cuts clean
          </h1>
          <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>
            Drop a file. Drag the handle, zoom to 800%. The left side is the original pixels,
            the right side is the vector we&apos;d give you back.
          </p>
        </div>
        <Converter />
      </section>

      <section
        style={{
          display: "grid",
          gap: "var(--space-5)",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
        }}
      >
        <Audience title="Selling prints and shirts">
          Drop a week of designs in one go — up to 500 files — and get one zip back. Each file
          keeps its own name.
        </Audience>
        <Audience title="Cutting, engraving, embroidery">
          Say how wide it should be in millimetres or inches, and the DXF opens at that size in
          Design Space or LightBurn.
        </Audience>
        <Audience title="Print shops and studios">
          A client&apos;s 400 px JPEG comes back as press-ready art, with the colours it started
          with. Files are deleted, not kept.
        </Audience>
      </section>

      <section
        style={{
          display: "flex",
          gap: 20,
          flexWrap: "wrap",
          fontSize: "var(--text-xs)",
          color: "var(--ink-500)",
          borderTop: "1px solid var(--ink-100)",
          borderBottom: "1px solid var(--ink-100)",
          padding: "var(--space-4) 0",
        }}
      >
        <span>Out: SVG · PDF · EPS · DXF · PNG</span>
        <span>In: PNG, JPEG, WEBP, TIFF, GIF, BMP, HEIC</span>
        <span>
          Photographs don&apos;t vectorize cleanly, and we say so rather than selling you a mess.
        </span>
      </section>

      <Pricing />
    </div>
  );
}

function Audience({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      {/* h2, not h3: the visual size is a style choice, the level is a
          promise to a screen reader that there is an h2 above it. */}
      <h2 style={{ fontSize: "var(--text-h3)", margin: "0 0 6px" }}>{title}</h2>
      <p style={{ color: "var(--ink-500)", margin: 0 }}>{children}</p>
    </div>
  );
}

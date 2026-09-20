import type { Metadata } from "next";
import Converter from "@/components/Converter";

export const metadata: Metadata = {
  title: "Convert an image to vector",
  description:
    "Upload a PNG or JPEG and get a clean SVG, DXF, PDF or EPS. Free watermarked preview, pay only to download.",
};

export default function ConvertPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-5)" }}>
      <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Convert an image to vector</h1>
      <Converter />
    </div>
  );
}

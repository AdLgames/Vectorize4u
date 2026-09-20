import type { Metadata } from "next";
import Converter from "@/components/Converter";

export const metadata: Metadata = {
  title: "Convert an image to vector",
  description:
    "Upload a PNG or JPEG and get a clean SVG, DXF, PDF or EPS. Free watermarked preview, pay only to download.",
};

export default function ConvertPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <Converter heading="Convert an image to vector" />
    </div>
  );
}

import type { Metadata } from "next";
import BatchRunner from "@/components/BatchRunner";

export const metadata: Metadata = {
  title: "Batch convert images to vector",
  description:
    "Convert up to 500 images in one run. Progress is stored server-side, so closing the tab doesn't lose the job, and any file can be retried on its own.",
};

export default function BatchPage() {
  return (
    <div style={{ padding: "40px 20px 64px", display: "grid", gap: "var(--space-5)" }}>
      <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>Batch</h1>
      <p style={{ color: "var(--ink-500)", margin: 0, maxWidth: "60ch" }}>
        Drop up to 500 files. Each one is converted independently, so a single bad file
        never takes the run down with it — and closing this tab doesn’t lose your work.
      </p>
      <BatchRunner />
    </div>
  );
}

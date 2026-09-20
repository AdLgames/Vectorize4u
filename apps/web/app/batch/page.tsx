import type { Metadata } from "next";
import BatchRunner from "@/components/BatchRunner";

export const metadata: Metadata = {
  title: "Batch convert images to vector",
  description:
    "Convert up to 500 images in one run. Progress is stored server-side, so closing the tab doesn't lose the job, and any file can be retried on its own.",
};

export default function BatchPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Batch conversion</h1>
      <p className="max-w-2xl text-slate-600 dark:text-slate-300">
        Drop up to 500 files. Each one is converted independently, so a single bad file
        never takes the run down with it — and closing this tab doesn’t lose your work.
      </p>
      <BatchRunner />
    </div>
  );
}

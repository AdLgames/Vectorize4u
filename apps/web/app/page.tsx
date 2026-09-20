import Link from "next/link";
import { SoftwareApplicationLd } from "@/components/JsonLd";

/**
 * The home page states the positioning of §0 plainly: we are not selling
 * "an SVG converter" — vtracer is free and Illustrator has Image Trace.
 * We sell batch, cut-correctness and honesty about quality.
 */

export default function Home() {
  return (
    <div className="mx-auto max-w-6xl space-y-16 px-4 py-14">
      <SoftwareApplicationLd
        name="Vectorize"
        description="Batch raster-to-vector conversion with cutter-safe output and an exposed quality score."
      />

      <section className="space-y-6">
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
          Vector files that work on the machine, not just on screen.
        </h1>
        <p className="max-w-2xl text-lg text-slate-600 dark:text-slate-300">
          Convert logos and line art to SVG, DXF, PDF and EPS — hundreds at a time,
          at the physical size you specify, with a quality score you can actually see.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link
            href="/convert"
            className="rounded bg-blue-600 px-5 py-3 font-medium text-white hover:bg-blue-700"
          >
            Convert an image free
          </Link>
          <Link
            href="/convert-for-cricut"
            className="rounded border border-slate-300 px-5 py-3 font-medium hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            For Cricut &amp; laser cutters
          </Link>
        </div>
      </section>

      <section className="grid gap-8 sm:grid-cols-3">
        <Feature title="Batch, properly">
          Drop 500 files. Progress is stored on our side, so closing the tab doesn’t
          lose the run, and any single file can be retried on its own.
        </Feature>
        <Feature title="Opens at the right size">
          Tell us how wide it should be and the SVG carries real units; the DXF
          carries absolute units and flattened curves your cutter can read.
        </Feature>
        <Feature title="An honest score">
          Every result comes with a match percentage, a point count and plain warnings
          when the source won’t trace well. No surprises after you pay.
        </Feature>
      </section>

      <section className="space-y-4 rounded-lg bg-slate-50 p-6 dark:bg-slate-900">
        <h2 className="text-xl font-semibold">What we don’t do</h2>
        <ul className="list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300">
          <li>
            <strong>Photographs.</strong> They don’t vectorize cleanly and never will. We
            detect them and say so rather than selling you a mess.
          </li>
          <li>
            <strong>Stitch files.</strong> We produce clean artwork for Ink/Stitch, Hatch
            and similar. Digitizing is a different problem and we don’t pretend otherwise.
          </li>
          <li>
            <strong>True gradients.</strong> Tracing bands a gradient into steps. We do the
            best banded trace and warn you.
          </li>
        </ul>
      </section>
    </div>
  );
}

function Feature({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-slate-600 dark:text-slate-300">{children}</p>
    </div>
  );
}

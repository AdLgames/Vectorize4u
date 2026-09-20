"use client";

import type { Job } from "@/lib/api";
import { Button, Notice, type Tone } from "./ui";

/**
 * The "this will not go well" moments, in the customer's words.
 *
 * Every notice says three things: what is wrong, what to do instead, and —
 * crucially — that nothing has been charged. §3.2: being honest here is
 * what prevents refund requests.
 */

type Copy = {
  tone: Tone;
  title: (job: Job) => string;
  body: (job: Job) => string;
  cta?: string;
  alt?: string;
};

const NOTICES: Record<string, Copy> = {
  photo_input: {
    tone: "amber",
    title: () => "This looks like a photograph",
    body: () =>
      "Tracing turns soft gradients and shadows into flat blocks, so the result loses detail. Line art, logos and flat illustrations work best. You can still download it, or try raising the colour count.",
    cta: "Try more colours",
    alt: "Pick a different file",
  },
  source_resolution_low: {
    tone: "amber",
    title: (job) =>
      job.quality
        ? `Your file is small — ${job.source_width ?? "?"} × ${job.source_height ?? "?"} px`
        : "Your file is small",
    body: () =>
      "We upscaled it before tracing, which helps, but detail that isn't in the original can't be recovered. If you have a bigger version of this image, use that instead. Nothing is charged until you download.",
    cta: "Upload a bigger file",
    alt: "Download anyway",
  },
  gradients_banded: {
    tone: "amber",
    title: () => "Gradients become colour steps",
    body: () =>
      "Vector files can't hold a smooth gradient the way a photo can, so it is split into bands. We use the finest steps the tracer supports.",
  },
  physical_size_assumed: {
    tone: "amber",
    title: () => "Set the size before you cut",
    body: () =>
      "This file has no reliable physical size, so we assumed one. Tell us how wide it should be and the SVG and DXF will open at that size in Design Space or LightBurn.",
  },
  simplify_skipped_large: {
    tone: "amber",
    title: () => "Too complex to simplify",
    body: () =>
      "This traced to a very large number of points. It will open, but it is not suited to a cutting machine.",
  },
  alpha_premultiplied_fixed: {
    tone: "cyan",
    title: () => "Fixed the transparency",
    body: () =>
      "Your PNG stored its transparency in a way that causes dark halos around soft edges. We corrected it.",
  },
  cmyk_converted: {
    tone: "cyan",
    title: () => "Converted from CMYK",
    body: () => "Colours were converted to sRGB. Check brand colours before printing.",
  },
  exif_rotated: {
    tone: "cyan",
    title: () => "Rotated to match the original",
    body: () => "Your photo carried a rotation flag, so we applied it before tracing.",
  },
  preprocess_backed_off: {
    tone: "cyan",
    title: () => "Cleaning was dialled back",
    body: () => "Our filters were changing the artwork too much, so we used a lighter touch.",
  },
  node_spacing_enforced: {
    tone: "cyan",
    title: () => "Adjusted for cutting",
    body: () =>
      "Points closer together than a blade can follow were merged — dense clusters make vinyl tear.",
  },
};

/** Ordered so the most consequential warning is the one that gets the actions. */
const PRIORITY = [
  "photo_input",
  "source_resolution_low",
  "simplify_skipped_large",
  "gradients_banded",
  "physical_size_assumed",
];

export function PrimaryNotice({
  job,
  onAction,
  onAlt,
}: {
  job: Job;
  onAction?: (code: string) => void;
  onAlt?: () => void;
}) {
  const code = PRIORITY.find((c) => job.warnings.includes(c));
  if (!code) return null;
  const copy = NOTICES[code];
  return (
    <Notice
      tone={copy.tone}
      title={copy.title(job)}
      actions={
        copy.cta && (
          <>
            <Button size="sm" variant="primary" onClick={() => onAction?.(code)}>
              {copy.cta}
            </Button>
            {copy.alt && (
              <Button size="sm" variant="secondary" onClick={onAlt}>
                {copy.alt}
              </Button>
            )}
          </>
        )
      }
    >
      {copy.body(job)}
    </Notice>
  );
}

/** Everything else, as a quiet list under the score. */
export function SecondaryNotices({ job }: { job: Job }) {
  const primary = PRIORITY.find((c) => job.warnings.includes(c));
  const rest = job.warnings.filter((c) => c !== primary && NOTICES[c]);
  if (rest.length === 0) return null;
  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
      {rest.map((code) => {
        const copy = NOTICES[code];
        return (
          <li key={code} style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)" }}>
            <strong style={{ color: "var(--ink-700)" }}>{copy.title(job)}.</strong>{" "}
            {copy.body(job)}
          </li>
        );
      })}
    </ul>
  );
}

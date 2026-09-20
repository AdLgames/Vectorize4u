"use client";

import { useCallback, useRef, useState } from "react";
import {
  ApiError,
  type Job,
  type JobOptions,
  createUpload,
  putToStorage,
  startPreview,
  tweakJob,
  unlockJob,
  waitForJob,
} from "@/lib/api";
import CompareSlider from "./CompareSlider";
import QualityPanel from "./QualityPanel";

/**
 * The conversion flow of §7: free preview, paid download.
 *
 * 1. Drag-drop → immediate client-side thumbnail → presigned upload to R2.
 * 2. Preview on the preview lane. Stage A is whatever comes back first;
 *    stage B replaces it in place. **The job the user sees at the end IS the
 *    job they buy** — there is no separate "real" run after payment.
 * 3. Zoomable side-by-side slider.
 * 4. Download → sign in → unlock → signed URLs.
 *
 * `cutIntent` makes the physical-size question mandatory before anything is
 * downloaded: cut-intent pages and any DXF download must ask "How wide
 * should this be?" (§3.8).
 */

export type ConverterProps = {
  cutIntent?: boolean;
  defaultFormats?: string[];
  heading?: string;
};

type Phase = "idle" | "uploading" | "tracing" | "ready" | "error";

export default function Converter({
  cutIntent = false,
  defaultFormats = ["svg"],
  heading = "Convert an image",
}: ConverterProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [job, setJob] = useState<Job | null>(null);
  const [thumbnail, setThumbnail] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState({ width: 640, height: 480 });
  const [message, setMessage] = useState<string | null>(null);
  const [previewsLeft, setPreviewsLeft] = useState<number | null>(null);
  const [turnstile, setTurnstile] = useState(false);
  const [refining, setRefining] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [token] = useState<string | null>(null); // wired to the auth provider in Phase 4
  const [options, setOptions] = useState<JobOptions>({
    format: defaultFormats,
    detail: "balanced",
    units: "mm",
    output_width: null,
    quality_tier: "standard",
  });
  const uploadRef = useRef<string | null>(null);

  const needsWidth = cutIntent || (options.format ?? []).includes("dxf");
  const widthMissing = needsWidth && !options.output_width;

  const handleFile = useCallback(
    async (file: File) => {
      setMessage(null);
      setJob(null);
      setPhase("uploading");

      // Immediate client-side thumbnail: no layout shift, and the user sees
      // something within a frame of the drop (§7.1).
      const objectUrl = URL.createObjectURL(file);
      setThumbnail(objectUrl);
      const probe = new Image();
      probe.onload = () => setDimensions({ width: probe.naturalWidth, height: probe.naturalHeight });
      probe.src = objectUrl;

      try {
        const slot = await createUpload(file, token);
        await putToStorage(slot.put_url, file, slot.headers);
        uploadRef.current = slot.upload_id;

        setPhase("tracing");
        const { job: started, previewsRemaining, turnstileRequired } = await startPreview(
          slot.upload_id,
          options,
          token,
        );
        setPreviewsLeft(previewsRemaining);
        setTurnstile(turnstileRequired);

        if (started.status === "complete" || started.status === "failed") {
          setJob(started);
          setPhase(started.status === "failed" ? "error" : "ready");
          if (started.status === "failed") {
            setMessage(errorCopy(started.error_code));
          }
          return;
        }

        // Not finished inside the hold window. Keep the UI live and poll.
        setRefining(true);
        const finished = await waitForJob(started.id, token);
        setRefining(false);
        setJob(finished);
        setPhase(finished.status === "complete" ? "ready" : "error");
        if (finished.status !== "complete") setMessage(errorCopy(finished.error_code));
      } catch (error) {
        setPhase("error");
        setMessage(
          error instanceof ApiError
            ? errorCopy(error.problem.error_code, error.problem.detail)
            : "Something went wrong. Please try again.",
        );
      }
    },
    [options, token],
  );

  const applyTweak = useCallback(
    async (next: JobOptions) => {
      if (!job) return;
      setOptions(next);
      setRefining(true);
      try {
        // A tweak re-runs a *single* trace as a child job, not the full
        // search — the point is instant feedback (§7.6).
        const started = await tweakJob(job.id, next, token);
        const finished =
          started.status === "complete" ? started : await waitForJob(started.id, token);
        setJob(finished);
      } catch (error) {
        setMessage(error instanceof ApiError ? error.problem.detail : "Tweak failed.");
      } finally {
        setRefining(false);
      }
    },
    [job, token],
  );

  const download = useCallback(async () => {
    if (!job) return;
    if (widthMissing) {
      setMessage("Tell us how wide this should be before downloading a cut file.");
      return;
    }
    if (!token) {
      // Sign-in gate. The unlock endpoint is what actually spends a credit;
      // this is only the redirect.
      setMessage("Sign in to download. Your preview is kept — you'll come back to this result.");
      return;
    }
    try {
      setJob(await unlockJob(job.id, token));
    } catch (error) {
      if (error instanceof ApiError && error.problem.error_code === "insufficient_credits") {
        setMessage("You're out of downloads. Add a credit pack or upgrade your plan.");
        return;
      }
      setMessage(error instanceof ApiError ? error.problem.detail : "Unlock failed.");
    }
  }, [job, token, widthMissing]);

  return (
    <section className="space-y-6" aria-labelledby="converter-heading">
      <h1 id="converter-heading" className="text-2xl font-semibold tracking-tight">
        {heading}
      </h1>

      {/* The drop zone and the result occupy the same box, so nothing shifts
          when an image lands (§7 must-haves). */}
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void handleFile(file);
        }}
        className={`rounded-lg border-2 border-dashed p-6 transition-colors ${
          dragOver
            ? "border-blue-500 bg-blue-50 dark:bg-blue-950/30"
            : "border-slate-300 dark:border-slate-700"
        }`}
      >
        {phase === "idle" || !thumbnail ? (
          <div className="flex min-h-[18rem] flex-col items-center justify-center gap-3 text-center">
            <p className="text-lg font-medium">Drop an image here</p>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              PNG, JPEG, WEBP, TIFF, GIF, BMP or HEIC. Up to 25 MB.
            </p>
            <label className="cursor-pointer rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
              Choose a file
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void handleFile(file);
                }}
              />
            </label>
          </div>
        ) : (
          <div className="space-y-6">
            {phase === "ready" && job ? (
              <CompareSlider
                jobId={job.id}
                sourceUrl={thumbnail}
                sourceWidth={dimensions.width}
                sourceHeight={dimensions.height}
                refining={refining}
              />
            ) : (
              <div className="flex min-h-[18rem] items-center justify-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={thumbnail}
                  alt="Your image, being converted"
                  className="max-h-72 opacity-60"
                />
                <p className="ml-4 text-sm" role="status" aria-live="polite">
                  {phase === "uploading" ? "Uploading…" : "Tracing…"}
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {message && (
        <p role="alert" className="rounded bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
          {message}
        </p>
      )}

      {turnstile && (
        <p className="rounded bg-slate-100 p-3 text-sm dark:bg-slate-800">
          You’ve used several free previews. We’ll ask for a quick human check on the
          next one.
        </p>
      )}

      {previewsLeft !== null && previewsLeft < 5 && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {previewsLeft} free previews left this hour.
        </p>
      )}

      {job && job.status === "complete" && (
        <div className="grid gap-8 lg:grid-cols-[2fr_1fr]">
          <QualityPanel job={job} />

          <aside className="space-y-4">
            <h2 className="text-lg font-semibold">Download</h2>

            {needsWidth && (
              <div className="space-y-1">
                <label htmlFor="width" className="block text-sm font-medium">
                  How wide should this be?
                </label>
                <div className="flex gap-2">
                  <input
                    id="width"
                    type="number"
                    min={1}
                    step="0.1"
                    value={options.output_width ?? ""}
                    onChange={(event) =>
                      setOptions({
                        ...options,
                        output_width: event.target.value ? Number(event.target.value) : null,
                      })
                    }
                    className="w-28 rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                    aria-describedby="width-help"
                  />
                  <select
                    value={options.units}
                    onChange={(event) =>
                      setOptions({ ...options, units: event.target.value as "mm" | "in" })
                    }
                    className="rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                    aria-label="Units"
                  >
                    <option value="mm">mm</option>
                    <option value="in">in</option>
                  </select>
                </div>
                <p id="width-help" className="text-xs text-slate-500 dark:text-slate-400">
                  Cutting software disagrees about files with no stated size. Set this and
                  it opens correctly in Cricut Design Space and LightBurn.
                </p>
              </div>
            )}

            {job.unlocked ? (
              <ul className="space-y-2">
                {Object.entries(job.outputs).map(([format, url]) => (
                  <li key={format}>
                    <a
                      href={url}
                      className="inline-block rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900"
                      download
                    >
                      Download .{format}
                    </a>
                  </li>
                ))}
                <li className="text-xs text-slate-500 dark:text-slate-400">
                  Re-downloads and other formats are free while this job is kept.
                </li>
              </ul>
            ) : (
              <button
                type="button"
                onClick={() => void download()}
                disabled={widthMissing}
                className="w-full rounded bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                Unlock download — 1 credit
              </button>
            )}

            <details
              open={advancedOpen}
              onToggle={(event) => setAdvancedOpen((event.target as HTMLDetailsElement).open)}
              className="rounded border border-slate-200 p-3 dark:border-slate-700"
            >
              <summary className="cursor-pointer text-sm font-medium">Advanced</summary>
              <div className="mt-3 space-y-3 text-sm">
                <label className="block">
                  Detail
                  <select
                    value={options.detail}
                    onChange={(event) =>
                      void applyTweak({
                        ...options,
                        detail: event.target.value as JobOptions["detail"],
                      })
                    }
                    className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                  >
                    <option value="low">Low — fewest points</option>
                    <option value="balanced">Balanced</option>
                    <option value="high">High — most detail</option>
                  </select>
                </label>
                <label className="block">
                  Colours
                  <input
                    type="number"
                    min={2}
                    max={64}
                    value={options.max_colors ?? ""}
                    placeholder="auto"
                    onChange={(event) =>
                      setOptions({
                        ...options,
                        max_colors: event.target.value ? Number(event.target.value) : null,
                      })
                    }
                    onBlur={() => void applyTweak(options)}
                    className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                  />
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={options.simplify ?? true}
                    onChange={(event) =>
                      void applyTweak({ ...options, simplify: event.target.checked })
                    }
                  />
                  Simplify paths
                </label>
                <fieldset>
                  <legend className="font-medium">Formats</legend>
                  {["svg", "dxf", "pdf", "eps", "png"].map((format) => (
                    <label key={format} className="mr-3 inline-flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={(options.format ?? []).includes(format)}
                        onChange={(event) => {
                          const current = new Set(options.format ?? ["svg"]);
                          if (event.target.checked) current.add(format);
                          else current.delete(format);
                          current.add("svg");
                          setOptions({ ...options, format: [...current] });
                        }}
                      />
                      .{format}
                    </label>
                  ))}
                </fieldset>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Every tweak re-runs one trace, not the whole search — and it’s still the
                  same image, so it never costs a second credit.
                </p>
              </div>
            </details>
          </aside>
        </div>
      )}
    </section>
  );
}

function errorCopy(code: string | null, fallback?: string): string {
  switch (code) {
    case "unsupported_format":
      return "We couldn't read that file. Try a PNG or JPEG.";
    case "image_too_large":
      return "That file is over 25 MB. Try exporting it smaller.";
    case "unsafe_url":
      return "That URL can't be fetched.";
    case "tracer_crash":
      return "Something broke on our side while tracing. We've been alerted — please try again.";
    default:
      return fallback ?? "That didn't work. Please try a different file.";
  }
}

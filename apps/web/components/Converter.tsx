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
import AdjustPanel from "./AdjustPanel";
import { useAuth } from "./AuthProvider";
import DownloadPanel from "./DownloadPanel";
import ScoreCard from "./ScoreCard";
import Viewer from "./Viewer";
import { PrimaryNotice, SecondaryNotices } from "./WarningNotice";
import SignIn from "./SignIn";
import { Button, Card, Muted, Notice } from "./ui";

/**
 * The conversion flow of §7: free preview, paid download.
 *
 * Drop → client-side thumbnail (no layout shift) → presigned upload straight
 * to storage → preview on the preview lane → zoomable comparison → unlock.
 *
 * **The job the user sees at the end is the job they buy.** There is no
 * separate "real" run after payment; tweaks are child jobs of the same
 * source image and never cost a second credit.
 */

export type ConverterProps = {
  cutIntent?: boolean;
  defaultFormats?: string[];
  compact?: boolean;
};

type Phase = "idle" | "uploading" | "tracing" | "ready" | "error";

export default function Converter({
  cutIntent = false,
  defaultFormats = ["svg"],
  compact = false,
}: ConverterProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [job, setJob] = useState<Job | null>(null);
  const [thumbnail, setThumbnail] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string>("");
  const [dimensions, setDimensions] = useState({ width: 640, height: 480 });
  const [message, setMessage] = useState<string | null>(null);
  const [previewsLeft, setPreviewsLeft] = useState<number | null>(null);
  const [turnstile, setTurnstile] = useState(false);
  const [busy, setBusy] = useState(false);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const { token, signedIn, credits, refreshCredits } = useAuth();
  const [options, setOptions] = useState<JobOptions>({
    format: defaultFormats,
    detail: "balanced",
    units: "mm",
    output_width: null,
    quality_tier: "standard",
  });
  const inputRef = useRef<HTMLInputElement | null>(null);

  const reset = useCallback(() => {
    setPhase("idle");
    setJob(null);
    setThumbnail(null);
    setMessage(null);
  }, []);

  const handleFile = useCallback(
    async (file: File) => {
      setMessage(null);
      setJob(null);
      setFileName(file.name);
      setPhase("uploading");

      const objectUrl = URL.createObjectURL(file);
      setThumbnail(objectUrl);
      const probe = new Image();
      probe.onload = () =>
        setDimensions({ width: probe.naturalWidth, height: probe.naturalHeight });
      probe.src = objectUrl;

      try {
        const slot = await createUpload(file, token);
        await putToStorage(slot.put_url, file, slot.headers);

        setPhase("tracing");
        const { job: started, previewsRemaining, turnstileRequired } = await startPreview(
          slot.upload_id,
          options,
          token,
        );
        setPreviewsLeft(previewsRemaining);
        setTurnstile(turnstileRequired);

        const finished =
          started.status === "complete" || started.status === "failed"
            ? started
            : await waitForJob(started.id, token);

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

  const applyOptions = useCallback(
    async (next: JobOptions, retrace: boolean) => {
      setOptions(next);
      if (!retrace || !job) return;
      setBusy(true);
      try {
        const started = await tweakJob(job.id, next, token);
        const finished =
          started.status === "complete" ? started : await waitForJob(started.id, token);
        setJob(finished);
        if (finished.status !== "complete") setMessage(errorCopy(finished.error_code));
      } catch (error) {
        setMessage(error instanceof ApiError ? error.problem.detail : "That re-trace failed.");
      } finally {
        setBusy(false);
      }
    },
    [job, token],
  );

  const unlock = useCallback(async () => {
    if (!job) return;
    if (!token) {
      // The preview survives sign-in: the job is already on the server and
      // becomes theirs at unlock, so they come straight back to this result
      // rather than re-uploading.
      setNeedsSignIn(true);
      return;
    }
    setBusy(true);
    setNeedsSignIn(false);
    try {
      setJob(await unlockJob(job.id, token));
      // The header shows this number too; leaving it stale after a purchase
      // reads as "my credit was not taken".
      await refreshCredits();
    } catch (error) {
      if (error instanceof ApiError && error.problem.error_code === "insufficient_credits") {
        setMessage("You're out of downloads. A $9 credit pack adds 50 that never expire.");
      } else {
        setMessage(error instanceof ApiError ? error.problem.detail : "Unlock failed.");
      }
    } finally {
      setBusy(false);
    }
  }, [job, token, refreshCredits]);

  const processing =
    phase === "uploading"
      ? { label: "Uploading", sub: fileName, progress: 0.25 }
      : phase === "tracing"
        ? {
            label: "Tracing candidates",
            sub: "Scoring each one against your original",
            progress: 0.68,
          }
        : null;

  if (phase === "idle" || !thumbnail) {
    return (
      <DropZone
        compact={compact}
        dragOver={dragOver}
        setDragOver={setDragOver}
        onFile={handleFile}
        inputRef={inputRef}
      />
    );
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-5)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: "var(--text-h3)", margin: 0 }}>{fileName}</h2>
        <Muted size="xs">
          {dimensions.width} × {dimensions.height} px
          {job?.quality ? ` · ${job.quality.paths} shapes · ${job.quality.nodes} nodes` : ""}
        </Muted>
        <div style={{ marginLeft: "auto" }}>
          <Button size="sm" onClick={reset}>
            Convert another
          </Button>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gap: "var(--space-5)",
          gridTemplateColumns: compact ? "minmax(0,1fr)" : "minmax(0,2fr) minmax(300px,1fr)",
          alignItems: "start",
        }}
      >
        <Card padded={false} style={{ overflow: "hidden", background: "var(--ink-25)" }}>
          <Viewer
            jobId={job?.status === "complete" ? job.id : null}
            sourceUrl={thumbnail}
            sourceWidth={dimensions.width}
            sourceHeight={dimensions.height}
            height={compact ? 340 : 480}
            rightLabel={processing ? "Working" : "Vector"}
            processing={processing}
          />
          <div
            style={{
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              padding: "8px 12px",
              borderTop: "1px solid var(--ink-100)",
              fontSize: "var(--text-xs)",
              color: "var(--ink-400)",
            }}
          >
            <span>Drag the handle · scroll or pinch to zoom · drag the image to pan</span>
            <span style={{ marginLeft: "auto" }}>
              Preview is watermarked. The file you download is not.
            </span>
          </div>
        </Card>

        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          {message && (
            <Notice tone="magenta" title="Heads up">
              {message}
            </Notice>
          )}

          {job?.status === "complete" && (
            <>
              {needsSignIn && !signedIn && (
                <SignIn reason="Sign in to download" compact />
              )}
              <PrimaryNotice
                job={job}
                onAction={(code) => {
                  if (code === "photo_input") {
                    void applyOptions({ ...options, max_colors: 24 }, true);
                  } else {
                    inputRef.current?.click();
                  }
                }}
                onAlt={reset}
              />
              <ScoreCard job={job} />
              <SecondaryNotices job={job} />
              <DownloadPanel
                job={job}
                cutIntent={cutIntent}
                options={options}
                onChange={(next) => void applyOptions(next, false)}
                onUnlock={() => void unlock()}
                credits={credits}
                busy={busy}
              />
              <AdjustPanel
                options={options}
                onChange={(next) => void applyOptions(next, true)}
                busy={busy}
              />
            </>
          )}

          {turnstile && (
            <Muted size="xs">
              You&apos;ve used several free previews. We&apos;ll ask for a quick human check on
              the next one.
            </Muted>
          )}
          {previewsLeft !== null && previewsLeft < 5 && (
            <Muted size="xs">{previewsLeft} free previews left this hour.</Muted>
          )}
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="sr-only"
        style={{ display: "none" }}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleFile(file);
        }}
      />
    </div>
  );
}

function DropZone({
  compact,
  dragOver,
  setDragOver,
  onFile,
  inputRef,
}: {
  compact: boolean;
  dragOver: boolean;
  setDragOver: (v: boolean) => void;
  onFile: (file: File) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  return (
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
        if (file) onFile(file);
      }}
      style={{
        border: `1px dashed ${dragOver ? "var(--cyan)" : "var(--ink-200)"}`,
        background: dragOver ? "var(--cyan-soft)" : "var(--ink-0)",
        borderRadius: "var(--radius-lg)",
        padding: compact ? "var(--space-5)" : "var(--space-6)",
        display: "flex",
        alignItems: "center",
        gap: "var(--space-4)",
        flexWrap: "wrap",
        transition: `background var(--dur-base) var(--ease-out)`,
      }}
    >
      <div style={{ flex: 1, minWidth: 240 }}>
        <div style={{ fontWeight: 500, color: "var(--ink-900)" }}>
          Drop a file here, or browse
        </div>
        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-500)" }}>
          PNG, JPEG, WEBP, TIFF or HEIC up to 25 MB. No account needed to see the result.
        </div>
      </div>
      <Button
        variant="primary"
        size="lg"
        onClick={() => inputRef.current?.click()}
      >
        Choose a file
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
        }}
      />
    </div>
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
      return "The trace didn't finish. Your file is still here and no credit was used — run it again, or come back in a few minutes.";
    default:
      return fallback ?? "That didn't work. Please try a different file.";
  }
}

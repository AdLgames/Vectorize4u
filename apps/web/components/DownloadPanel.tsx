"use client";

import type { Job, JobOptions } from "@/lib/api";
import { Button, Card, Field } from "./ui";

/**
 * Format picker, cut size, and the download gate.
 *
 * Two things this panel must get right:
 *
 * - **DXF forces the size question** (§3.8). A confidently wrong physical
 *   size is the one failure a cutter user cannot recover from, so the
 *   download button stays disabled until they answer.
 * - **The gate line is honest about what a credit buys**: other formats of
 *   the same file are free for the retention window, because it is one
 *   charge per source image, not per download.
 */

const FORMATS = [
  { id: "svg", label: "SVG" },
  { id: "pdf", label: "PDF" },
  { id: "eps", label: "EPS" },
  { id: "dxf", label: "DXF" },
  { id: "png", label: "PNG" },
] as const;

export default function DownloadPanel({
  job,
  options,
  onChange,
  onUnlock,
  credits,
  busy,
  cutIntent = false,
}: {
  job: Job;
  options: JobOptions;
  onChange: (next: JobOptions) => void;
  onUnlock: () => void;
  credits: number | null;
  busy: boolean;
  /** Cut-intent pages ask the size question even before DXF is picked. */
  cutIntent?: boolean;
}) {
  const selected = (options.format ?? ["svg"]).filter((f) => f !== "svg").concat("svg");
  const active = selected[0] === "svg" ? "svg" : selected[0];
  // §3.8: cut-intent pages and any DXF download ask "How wide should this
  // be?" before anything can be downloaded.
  const needsSize = cutIntent || selected.includes("dxf");
  const width = options.output_width;
  const sizeMissing = needsSize && !width;

  const aspect =
    job.source_width && job.source_height ? job.source_height / job.source_width : 0.673;
  const heightLine =
    width !== null && width !== undefined
      ? `Height follows at ${(width * aspect).toFixed(1)} ${options.units ?? "mm"}. Curves are flattened so cutters can read them.`
      : null;

  return (
    <Card>
      <div style={{ fontSize: "var(--text-sm)", fontWeight: 500, color: "var(--ink-900)" }}>
        Format
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0 var(--space-4)" }}>
        {FORMATS.map((format) => {
          const on = selected.includes(format.id);
          return (
            <button
              key={format.id}
              type="button"
              aria-pressed={on}
              onClick={() => {
                const next = new Set(options.format ?? ["svg"]);
                if (on && format.id !== "svg") next.delete(format.id);
                else next.add(format.id);
                next.add("svg"); // SVG is always produced (§3.8)
                onChange({ ...options, format: [...next] });
              }}
              style={{
                border: `1px solid ${on ? "var(--cyan-strong)" : "var(--ink-200)"}`,
                background: on ? "var(--cyan-strong)" : "var(--ink-0)",
                color: on ? "var(--cyan-fg)" : "var(--ink-700)",
                padding: "6px 12px",
                borderRadius: "var(--radius-sm)",
                fontSize: "var(--text-sm)",
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              {format.label}
            </button>
          );
        })}
      </div>

      {needsSize && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <Field label="What size should it cut at?" htmlFor="cut-width" hint={heightLine ?? undefined}>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                id="cut-width"
                type="number"
                min={1}
                step="0.1"
                value={width ?? ""}
                placeholder="90"
                onChange={(event) =>
                  onChange({
                    ...options,
                    output_width: event.target.value ? Number(event.target.value) : null,
                  })
                }
                style={{
                  width: 96,
                  padding: "8px 10px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--ink-200)",
                  background: "var(--ink-0)",
                  color: "var(--ink-900)",
                  fontSize: "var(--text-sm)",
                }}
              />
              <div style={{ display: "flex", gap: 4 }}>
                {(["mm", "in"] as const).map((unit) => (
                  <button
                    key={unit}
                    type="button"
                    aria-pressed={(options.units ?? "mm") === unit}
                    onClick={() => onChange({ ...options, units: unit })}
                    style={{
                      border: "1px solid var(--ink-200)",
                      background:
                        (options.units ?? "mm") === unit ? "var(--cyan-strong)" : "var(--ink-0)",
                      color: (options.units ?? "mm") === unit ? "var(--cyan-fg)" : "var(--ink-700)",
                      padding: "8px 12px",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "var(--text-sm)",
                      cursor: "pointer",
                    }}
                  >
                    {unit === "mm" ? "mm" : "inches"}
                  </button>
                ))}
              </div>
            </div>
          </Field>
        </div>
      )}

      {job.unlocked ? (
        <div style={{ display: "grid", gap: 8 }}>
          {Object.entries(job.outputs).map(([format, url]) => (
            <a
              key={format}
              href={url}
              download
              style={{
                display: "block",
                textAlign: "center",
                padding: "10px 14px",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--ink-200)",
                background: "var(--ink-0)",
                color: "var(--ink-900)",
                fontWeight: 500,
                fontSize: "var(--text-sm)",
                textDecoration: "none",
              }}
            >
              Download .{format}
            </a>
          ))}
          <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)", margin: 0 }}>
            Already paid for. Re-downloads and other formats of this file are free while we
            keep it.
          </p>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          <Button
            variant="primary"
            size="lg"
            full
            disabled={sizeMissing || busy}
            onClick={onUnlock}
          >
            {busy ? "Working…" : `Download ${active.toUpperCase()} — 1 credit`}
          </Button>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)", margin: 0 }}>
            {sizeMissing
              ? "Tell us how wide it should be first — a cut file with the wrong scale is worse than no file."
              : credits === null
                ? "The preview above is free and watermarked. Other formats of this file are free once you download one."
                : `You have ${credits} credits. The preview above is free and watermarked; other formats of this file are free once you download one.`}
          </p>
        </div>
      )}
    </Card>
  );
}

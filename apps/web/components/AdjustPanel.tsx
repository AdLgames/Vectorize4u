"use client";

import { useState } from "react";
import type { JobOptions } from "@/lib/api";
import { Card } from "./ui";

/**
 * "Adjust the trace" — §7.6's advanced panel.
 *
 * Every control re-runs a **single** trace as a child job, not the full
 * candidate search: the point is instant feedback. And because a child job
 * shares its parent's root_job_id, tweaking never costs a second credit —
 * which the panel says out loud, because otherwise people don't touch it.
 *
 * The labels are questions, not parameter names. "color_precision" means
 * nothing to a vinyl cutter; "How many colours?" does.
 */

const DETAIL_STEPS: Array<JobOptions["detail"]> = ["low", "low", "low", "balanced", "balanced", "balanced", "balanced", "high", "high", "high"];

export default function AdjustPanel({
  options,
  onChange,
  busy,
}: {
  options: JobOptions;
  onChange: (next: JobOptions) => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const colors = options.max_colors ?? 12;
  const despeckle = options.despeckle ?? 4;
  // Undefined means the engine chooses from the trace; 0 means the
  // customer chose "off". Those are different answers and the panel has
  // to be able to say which one is in force.
  const smoothingAuto = options.smoothing === undefined || options.smoothing === null;
  const smoothing = options.smoothing ?? 0;
  const detailIndex = Math.max(
    1,
    DETAIL_STEPS.findIndex((d) => d === (options.detail ?? "balanced")) + 1,
  );

  return (
    <Card padded={false}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "var(--space-4)",
          background: "transparent",
          border: 0,
          cursor: "pointer",
          fontSize: "var(--text-sm)",
          fontWeight: 500,
          color: "var(--ink-900)",
        }}
      >
        <span>Adjust the trace</span>
        <span style={{ color: "var(--ink-500)", fontWeight: 400 }}>
          {open
            ? "Hide"
            : `${colors} colours, detail ${detailIndex}${
                smoothingAuto ? "" : `, smoothing ${smoothing}`
              }`}
        </span>
      </button>

      {open && (
        <div
          style={{
            display: "grid",
            gap: "var(--space-5)",
            padding: "0 var(--space-4) var(--space-4)",
            borderTop: "1px solid var(--ink-100)",
            paddingTop: "var(--space-4)",
          }}
        >
          <Slider
            id="colors"
            label="How many colours?"
            display={String(colors)}
            help="Fewer colours cut and print more cleanly."
            min={2}
            max={24}
            value={colors}
            onCommit={(value) => onChange({ ...options, max_colors: value })}
          />
          <Slider
            id="detail"
            label="How detailed?"
            display={`${detailIndex} of 10`}
            help="Higher keeps small curves, and adds nodes."
            min={1}
            max={10}
            value={detailIndex}
            onCommit={(value) =>
              onChange({ ...options, detail: DETAIL_STEPS[value - 1] ?? "balanced" })
            }
          />
          <div style={{ display: "grid", gap: 6 }}>
            <Slider
              id="smoothing"
              label="Smooth out jagged edges"
              display={
                smoothingAuto ? "Automatic" : smoothing === 0 ? "Off" : `${smoothing} of 10`
              }
              help={
                smoothingAuto
                  ? "We pick this from your file: a low-resolution source comes back stepped, and this rounds the steps off. Drag to choose it yourself."
                  : smoothing === 0
                    ? "Off: edges follow your file exactly, pixel steps included."
                    : "Rounds off the pixel staircase in a low-resolution source. The match score drops on purpose — it is measured against those steps."
              }
              min={0}
              max={10}
              value={smoothing}
              onCommit={(value) => onChange({ ...options, smoothing: value })}
            />
            {!smoothingAuto && (
              <button
                type="button"
                onClick={() => onChange({ ...options, smoothing: undefined })}
                style={{
                  justifySelf: "start",
                  background: "transparent",
                  border: 0,
                  padding: 0,
                  cursor: "pointer",
                  fontSize: "var(--text-xs)",
                  color: "var(--ink-500)",
                  textDecoration: "underline",
                }}
              >
                Choose it for me again
              </button>
            )}
          </div>
          <Slider
            id="despeckle"
            label="Clean up specks"
            display={`${despeckle} of 16`}
            help={`Drops shapes smaller than about ${despeckle * 3} px.`}
            min={0}
            max={16}
            value={despeckle}
            onCommit={(value) => onChange({ ...options, despeckle: value })}
          />

          <label style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={options.keep_background === false}
              onChange={(event) =>
                onChange({ ...options, keep_background: !event.target.checked })
              }
              style={{ marginTop: 3 }}
            />
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
              Remove background
              <span
                style={{ display: "block", color: "var(--ink-500)", fontSize: "var(--text-xs)" }}
              >
                Drops the flat colour behind the artwork so it cuts as a shape.
              </span>
            </span>
          </label>

          <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)", margin: 0 }}>
            {busy
              ? "Re-tracing with your new settings…"
              : "Preview updates in about a second. Changing these doesn't cost a credit."}
          </p>
        </div>
      )}
    </Card>
  );
}

function Slider({
  id,
  label,
  display,
  help,
  min,
  max,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  display: string;
  help: string;
  min: number;
  max: number;
  value: number;
  onCommit: (value: number) => void;
}) {
  // Local state while dragging; the re-trace fires on release. Firing on
  // every input event would queue a job per pixel of slider travel.
  const [local, setLocal] = useState(value);
  const shown = local;
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <label htmlFor={id} style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
          {label}
        </label>
        <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)" }}>
          {shown === value ? display : String(shown)}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        value={shown}
        onChange={(event) => setLocal(Number(event.target.value))}
        onPointerUp={() => onCommit(local)}
        onKeyUp={() => onCommit(local)}
      />
      <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)" }}>{help}</span>
    </div>
  );
}

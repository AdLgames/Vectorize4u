"use client";

import { useState } from "react";
import type { Job } from "@/lib/api";
import { Button, Card, Meter, scoreColor, scoreTone } from "./ui";

/**
 * The exposed quality score (§6).
 *
 * "Exposing the quality score is a differentiator and a support-cost
 * reducer: it turns 'this looks bad' into a number both sides can see."
 *
 * Two rules the prototype gets right and we keep:
 *
 * - The number is always shown with its **score version**. Scores from
 *   different versions are not comparable, and a number without a version
 *   invites exactly that comparison.
 * - The internal term names never surface. "SSIM" and "edge F1" mean
 *   nothing to a print shop; "Shape match" and "Edge sharpness" do.
 */

export default function ScoreCard({ job }: { job: Job }) {
  const [open, setOpen] = useState(false);
  if (!job.quality) return null;
  const q = job.quality;
  const tone = scoreTone(q.total);

  const line =
    q.total >= 0.9
      ? "Very close to your original. Edges and colours held."
      : q.total >= 0.75
        ? "Close, but the source is soft, so edges were guessed in places."
        : "Parts of this were flattened. Look at the detail before you download.";

  return (
    <Card>
      <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-500)" }}>
        Match to your original
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "4px 0 10px" }}>
        <span style={{ fontSize: "var(--text-h2)", fontWeight: 600, color: scoreColor(q.total) }}>
          {q.total.toFixed(2)}
        </span>
        <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)" }}>
          of 1.00 · score {q.score_version}
        </span>
      </div>
      <Meter value={q.total} tone={tone} label="Match to your original" />
      <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-500)", margin: "10px 0 0" }}>
        {line}
      </p>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(!open)}
        ariaExpanded={open}
        style={{ paddingLeft: 0, marginTop: 6, color: "var(--cyan)" }}
      >
        {open ? "Hide the detail" : "What's behind this number?"}
      </Button>

      {open && (
        <dl
          style={{
            display: "grid",
            gap: 6,
            marginTop: "var(--space-3)",
            paddingTop: "var(--space-3)",
            borderTop: "1px solid var(--ink-100)",
            fontSize: "var(--text-sm)",
          }}
        >
          <Row label="Shape match" value={q.ssim.toFixed(2)} />
          <Row label="Colour match" value={q.color.toFixed(2)} />
          <Row label="Edge sharpness" value={q.edge_f1.toFixed(2)} />
          {q.alpha_iou !== null && q.alpha_iou !== undefined && (
            <Row label="Transparency match" value={q.alpha_iou.toFixed(2)} />
          )}
          <Row label="Nodes" value={q.nodes.toLocaleString()} />
          <Row label="Shapes" value={q.paths.toLocaleString()} />
        </dl>
      )}
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
      <dt style={{ color: "var(--ink-500)" }}>{label}</dt>
      <dd style={{ margin: 0, color: "var(--ink-900)", fontWeight: 500 }}>{value}</dd>
    </div>
  );
}

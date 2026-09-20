"use client";

import { useEffect, useMemo, useState } from "react";
import { minifySvg, type MinifyResult } from "@/lib/minifySvg";
import { Button, Card, Notice } from "@/components/ui";

/**
 * Runs entirely in the browser: nothing is uploaded, which is both the
 * honest privacy answer for someone pasting a client's logo and the reason
 * this can be free without costing us anything.
 */

const SAMPLE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <!-- exported from a drawing app -->
  <metadata>lots of editor metadata</metadata>
  <g id="unused-layer-1">
    <path d="M12.00000001 2.4999999 L21.1234567 19.9876543 L2.87654321 19.9876543 Z" fill="#0088a8"/>
  </g>
</svg>`;

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} kB`;
}

export default function SvgMinifier() {
  const [source, setSource] = useState(SAMPLE);
  const [precision, setPrecision] = useState(2);
  const [dropUnusedIds, setDropUnusedIds] = useState(true);
  const [dropEditorData, setDropEditorData] = useState(true);
  const [copied, setCopied] = useState(false);
  // DOMParser only exists in the browser, so the prerendered HTML has to be
  // the empty state — rendering a result on the server and a different one
  // after hydration is a mismatch React rightly complains about.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const outcome = useMemo<{ result?: MinifyResult; error?: string }>(() => {
    if (!mounted || !source.trim()) return {};
    try {
      return { result: minifySvg(source, { precision, dropUnusedIds, dropEditorData }) };
    } catch (error) {
      return { error: error instanceof Error ? error.message : "could not read that file" };
    }
  }, [mounted, source, precision, dropUnusedIds, dropEditorData]);

  const result = outcome.result;
  const saved = result ? Math.max(0, result.before - result.after) : 0;
  const percent = result && result.before ? Math.round((saved / result.before) * 100) : 0;

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setSource(await file.text());
    setCopied(false);
  };

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Card>
        <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
            <input
              type="file"
              accept=".svg,image/svg+xml"
              onChange={(event) => onFile(event.target.files?.[0])}
              style={{ fontSize: "var(--text-sm)" }}
            />
          </label>
          <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)" }}>
            or paste below — nothing leaves your browser
          </span>
        </div>

        <textarea
          value={source}
          onChange={(event) => {
            setSource(event.target.value);
            setCopied(false);
          }}
          spellCheck={false}
          aria-label="SVG source"
          style={{
            width: "100%",
            minHeight: 160,
            marginTop: "var(--space-3)",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: "var(--text-sm)",
            padding: "var(--space-3)",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--ink-200)",
            background: "var(--ink-25)",
            color: "var(--ink-900)",
            resize: "vertical",
          }}
        />

        <div
          style={{
            display: "flex",
            gap: "var(--space-4)",
            flexWrap: "wrap",
            alignItems: "center",
            marginTop: "var(--space-3)",
          }}
        >
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
            Decimal places{" "}
            <input
              type="range"
              min={0}
              max={5}
              value={precision}
              onChange={(event) => setPrecision(Number(event.target.value))}
              style={{ verticalAlign: "middle" }}
            />{" "}
            <strong style={{ fontVariantNumeric: "tabular-nums" }}>{precision}</strong>
          </label>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
            <input
              type="checkbox"
              checked={dropUnusedIds}
              onChange={(event) => setDropUnusedIds(event.target.checked)}
            />{" "}
            Drop unreferenced ids
          </label>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
            <input
              type="checkbox"
              checked={dropEditorData}
              onChange={(event) => setDropEditorData(event.target.checked)}
            />{" "}
            Drop editor metadata
          </label>
        </div>
      </Card>

      {outcome.error ? (
        <Notice tone="magenta" title="That is not valid SVG">
          {outcome.error}. Paste the contents of the .svg file, not a link to it.
        </Notice>
      ) : null}

      {result ? (
        <Card>
          <div
            style={{
              display: "flex",
              gap: "var(--space-5)",
              flexWrap: "wrap",
              alignItems: "baseline",
            }}
          >
            <div>
              <div style={{ fontSize: "var(--text-h2)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                {percent}%
              </div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)" }}>smaller</div>
            </div>
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-500)" }}>
              {bytes(result.before)} → {bytes(result.after)}
              {result.removed.length ? ` · removed ${result.removed.join(", ")}` : ""}
            </div>
          </div>

          {/* Before and after, rendered. A minifier you cannot check is a
              minifier you should not trust. */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: "var(--space-4)",
              margin: "var(--space-4) 0",
            }}
          >
            {[
              { label: "Before", markup: source },
              { label: "After", markup: result.svg },
            ].map((pane) => (
              <div key={pane.label} data-pane={pane.label.toLowerCase()}>
                <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)", marginBottom: 6 }}>
                  {pane.label}
                </div>
                <div
                  style={{
                    border: "1px solid var(--ink-100)",
                    borderRadius: "var(--radius-sm)",
                    padding: "var(--space-3)",
                    background: "var(--ink-0)",
                    minHeight: 120,
                    display: "grid",
                    placeItems: "center",
                  }}
                  // The markup is the user's own file, rendered back to them
                  // in their own browser; nothing here is shared or stored.
                  dangerouslySetInnerHTML={{ __html: pane.markup }}
                />
              </div>
            ))}
          </div>

          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <Button
              onClick={() => {
                navigator.clipboard?.writeText(result.svg);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy minified SVG"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                const url = URL.createObjectURL(
                  new Blob([result.svg], { type: "image/svg+xml" }),
                );
                const link = document.createElement("a");
                link.href = url;
                link.download = "minified.svg";
                link.click();
                URL.revokeObjectURL(url);
              }}
            >
              Download
            </Button>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

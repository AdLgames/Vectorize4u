"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Card, Notice } from "@/components/ui";

/**
 * SVG → PNG in the browser, via canvas. No upload, no queue, no cost.
 *
 * The one thing this tool must be honest about: an SVG that references a
 * web font or an external image will not carry them into the canvas, so the
 * PNG can differ from what the browser shows. We say so rather than let
 * someone ship a PNG with the wrong typeface in it.
 */

const SAMPLE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60">
  <rect width="120" height="60" rx="6" fill="#e4f4f8"/>
  <circle cx="34" cy="30" r="16" fill="#00738c"/>
  <rect x="60" y="18" width="42" height="24" rx="3" fill="#c01e62"/>
</svg>`;

export default function SvgToPng() {
  const [source, setSource] = useState(SAMPLE);
  const [width, setWidth] = useState(1024);
  const [transparent, setTransparent] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [png, setPng] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);

    const markup = source.trim();
    if (!markup) {
      setPng(null);
      return;
    }

    const blob = new Blob([markup], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const image = new Image();

    image.onload = () => {
      if (cancelled) return;
      // An SVG with only a viewBox has no intrinsic size in some browsers;
      // fall back to the viewBox ratio rather than rendering a 0×0 canvas.
      const ratio = image.height && image.width ? image.height / image.width : aspectFromViewBox(markup);
      const height = Math.max(1, Math.round(width * ratio));
      const canvas = canvasRef.current ?? document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.clearRect(0, 0, width, height);
      if (!transparent) {
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, width, height);
      }
      context.drawImage(image, 0, 0, width, height);
      setSize({ w: width, h: height });
      setPng(canvas.toDataURL("image/png"));
      URL.revokeObjectURL(url);
    };
    image.onerror = () => {
      if (cancelled) return;
      setError("that does not render as SVG");
      setPng(null);
      URL.revokeObjectURL(url);
    };
    image.src = url;

    return () => {
      cancelled = true;
      URL.revokeObjectURL(url);
    };
  }, [source, width, transparent]);

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Card>
        <input
          type="file"
          accept=".svg,image/svg+xml"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (file) setSource(await file.text());
          }}
          style={{ fontSize: "var(--text-sm)" }}
        />
        <textarea
          value={source}
          onChange={(event) => setSource(event.target.value)}
          spellCheck={false}
          aria-label="SVG source"
          style={{
            width: "100%",
            minHeight: 140,
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
            Width{" "}
            <select
              value={width}
              onChange={(event) => setWidth(Number(event.target.value))}
              style={{ fontSize: "var(--text-sm)", padding: "4px 6px" }}
            >
              {[256, 512, 1024, 2048, 4096].map((value) => (
                <option key={value} value={value}>
                  {value} px
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
            <input
              type="checkbox"
              checked={transparent}
              onChange={(event) => setTransparent(event.target.checked)}
            />{" "}
            Transparent background
          </label>
          {size ? (
            <span
              style={{
                fontSize: "var(--text-xs)",
                color: "var(--ink-500)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {size.w} × {size.h} px
            </span>
          ) : null}
        </div>
      </Card>

      {error ? (
        <Notice tone="magenta" title="That did not render">
          {error}. Web fonts and externally linked images do not travel with an SVG into a
          canvas — convert text to outlines first if your file uses them.
        </Notice>
      ) : null}

      {png ? (
        <Card>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={png}
            alt="PNG preview"
            style={{
              maxWidth: "100%",
              maxHeight: 320,
              display: "block",
              margin: "0 auto var(--space-4)",
              background:
                "repeating-conic-gradient(var(--ink-50) 0% 25%, var(--ink-0) 0% 50%) 50% / 16px 16px",
            }}
          />
          <Button
            variant="primary"
            onClick={() => {
              const link = document.createElement("a");
              link.href = png;
              link.download = `image-${size?.w ?? width}.png`;
              link.click();
            }}
          >
            Download PNG
          </Button>
        </Card>
      ) : null}

      <canvas ref={canvasRef} style={{ display: "none" }} />
    </div>
  );
}

function aspectFromViewBox(markup: string): number {
  const box = markup.match(/viewBox="[\s]*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/);
  if (!box) return 1;
  const w = Number(box[3]);
  const h = Number(box[4]);
  return w > 0 ? h / w : 1;
}

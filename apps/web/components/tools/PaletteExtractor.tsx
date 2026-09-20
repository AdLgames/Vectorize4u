"use client";

import { useCallback, useState } from "react";
import { Button, Card, Notice } from "@/components/ui";

/**
 * Pull the dominant colours out of an image, in the browser.
 *
 * Median cut rather than "count the most common pixels": a photograph has
 * no repeated exact values, so counting returns noise. Median cut splits
 * the colour cube along its widest axis until there are as many boxes as
 * swatches asked for, which is the same family of algorithm the engine's
 * quantiser uses — the answers should feel consistent between the two.
 */

type Swatch = { hex: string; share: number };

const MAX_SIDE = 160;

function toHex(r: number, g: number, b: number): string {
  return `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
}

function medianCut(pixels: number[][], count: number): Swatch[] {
  let boxes: number[][][] = [pixels];
  while (boxes.length < count) {
    // Split the box with the widest channel: that is where the most visible
    // difference is being lost by merging.
    let target = -1;
    let widest = -1;
    let channel = 0;
    boxes.forEach((box, index) => {
      if (box.length < 2) return;
      for (let c = 0; c < 3; c += 1) {
        let min = 255;
        let max = 0;
        for (const pixel of box) {
          if (pixel[c] < min) min = pixel[c];
          if (pixel[c] > max) max = pixel[c];
        }
        if (max - min > widest) {
          widest = max - min;
          target = index;
          channel = c;
        }
      }
    });
    if (target < 0 || widest <= 0) break;

    const box = [...boxes[target]].sort((a, b) => a[channel] - b[channel]);
    const middle = Math.floor(box.length / 2);
    boxes = [
      ...boxes.slice(0, target),
      box.slice(0, middle),
      box.slice(middle),
      ...boxes.slice(target + 1),
    ];
  }

  const total = pixels.length || 1;
  return boxes
    .filter((box) => box.length)
    .map((box) => {
      const sum = box.reduce((acc, p) => [acc[0] + p[0], acc[1] + p[1], acc[2] + p[2]], [0, 0, 0]);
      return {
        hex: toHex(sum[0] / box.length, sum[1] / box.length, sum[2] / box.length),
        share: box.length / total,
      };
    })
    .sort((a, b) => b.share - a.share);
}

export default function PaletteExtractor() {
  const [swatches, setSwatches] = useState<Swatch[] | null>(null);
  const [count, setCount] = useState(6);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pixels, setPixels] = useState<number[][] | null>(null);

  const extract = useCallback((samples: number[][], swatchCount: number) => {
    setSwatches(medianCut(samples, swatchCount));
  }, []);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setCopied(false);
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      const scale = Math.min(1, MAX_SIDE / Math.max(image.width, image.height));
      const w = Math.max(1, Math.round(image.width * scale));
      const h = Math.max(1, Math.round(image.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return;
      context.drawImage(image, 0, 0, w, h);
      const data = context.getImageData(0, 0, w, h).data;
      const samples: number[][] = [];
      for (let i = 0; i < data.length; i += 4) {
        // Transparent pixels have no colour worth reporting.
        if (data[i + 3] < 128) continue;
        samples.push([data[i], data[i + 1], data[i + 2]]);
      }
      if (!samples.length) {
        setError("every pixel in that image is transparent");
        setSwatches(null);
        return;
      }
      setPixels(samples);
      extract(samples, count);
      setPreview(url);
    };
    image.onerror = () => {
      setError("that file is not an image the browser can read");
      URL.revokeObjectURL(url);
    };
    image.src = url;
  };

  const hexList = swatches?.map((s) => s.hex).join(", ") ?? "";

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Card>
        <input
          type="file"
          accept="image/*"
          onChange={(event) => onFile(event.target.files?.[0])}
          style={{ fontSize: "var(--text-sm)" }}
        />
        <div style={{ marginTop: "var(--space-3)", fontSize: "var(--text-sm)", color: "var(--ink-800)" }}>
          How many colours{" "}
          <input
            type="range"
            min={2}
            max={16}
            value={count}
            onChange={(event) => {
              const next = Number(event.target.value);
              setCount(next);
              if (pixels) extract(pixels, next);
            }}
            style={{ verticalAlign: "middle" }}
          />{" "}
          <strong style={{ fontVariantNumeric: "tabular-nums" }}>{count}</strong>
        </div>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-500)", margin: "var(--space-2) 0 0" }}>
          The image is read in your browser and never uploaded.
        </p>
      </Card>

      {error ? (
        <Notice tone="magenta" title="Could not read that">
          {error}
        </Notice>
      ) : null}

      {swatches ? (
        <Card>
          <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={preview}
                alt=""
                style={{ width: 120, height: "auto", borderRadius: "var(--radius-sm)" }}
              />
            ) : null}
            <div style={{ display: "grid", gap: 6, flex: "1 1 240px" }}>
              {swatches.map((swatch) => (
                <div key={swatch.hex} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: 4,
                      background: swatch.hex,
                      border: "1px solid var(--ink-200)",
                      flexShrink: 0,
                    }}
                  />
                  <code style={{ fontSize: "var(--text-sm)", fontVariantNumeric: "tabular-nums" }}>
                    {swatch.hex}
                  </code>
                  <span
                    style={{
                      fontSize: "var(--text-xs)",
                      color: "var(--ink-500)",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {(swatch.share * 100).toFixed(1)}% of the image
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div style={{ marginTop: "var(--space-4)" }}>
            <Button
              onClick={() => {
                navigator.clipboard?.writeText(hexList);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy all hex values"}
            </Button>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

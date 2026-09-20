"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { tileUrl } from "@/lib/api";

/**
 * Side-by-side slider, zoomable to 800%.
 *
 * The zoom is the sales pitch (§7.3): the raster pixelates, the vector stays
 * sharp. Both sides are raster here — the right-hand side is a server-rendered
 * tile of the traced SVG, because **the SVG never reaches the browser before
 * unlock** (§7.4). An <svg> in the DOM is the download, watermark or not.
 */

const MAX_SCALE = 8; // the API caps this too; the UI must not promise more
const MIN_SCALE = 0.25;

export type CompareSliderProps = {
  jobId: string;
  sourceUrl: string;
  sourceWidth: number;
  sourceHeight: number;
  /** Shown while stage B replaces stage A in place ("refining…", §7.2). */
  refining?: boolean;
};

export default function CompareSlider({
  jobId,
  sourceUrl,
  sourceWidth,
  sourceHeight,
  refining = false,
}: CompareSliderProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [split, setSplit] = useState(50);
  const [scale, setScale] = useState(1);
  const [dragging, setDragging] = useState(false);
  // A higher-resolution tile takes a moment to render server-side. Until it
  // arrives the browser stretches the previous one, which looks like the
  // vector is pixelating — the exact opposite of the point being made.
  const [tileLoading, setTileLoading] = useState(false);

  const move = useCallback((clientX: number) => {
    const element = containerRef.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    const next = ((clientX - rect.left) / rect.width) * 100;
    setSplit(Math.min(100, Math.max(0, next)));
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (event: PointerEvent) => move(event.clientX);
    const onUp = () => setDragging(false);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [dragging, move]);

  // One tile covering the viewport. Panning is left to the browser's own
  // scroll: a tile grid is a Phase-8 optimisation, not a launch requirement.
  const tile = tileUrl(jobId, {
    x: 0,
    y: 0,
    w: Math.min(sourceWidth, 2048),
    h: Math.min(sourceHeight, 2048),
    scale,
  });

  const zoomPercent = Math.round(scale * 100);

  return (
    <div className="space-y-3">
      <div
        ref={containerRef}
        className="relative aspect-[4/3] w-full select-none overflow-auto rounded-lg border border-slate-200 bg-[repeating-conic-gradient(#f1f5f9_0%_25%,#ffffff_0%_50%)] bg-[length:20px_20px] dark:border-slate-700 dark:bg-[repeating-conic-gradient(#1e293b_0%_25%,#0f172a_0%_50%)]"
      >
        {/* Original, underneath. */}
        {/* max-w-none is load-bearing: Tailwind's preflight sets
            `img { max-width: 100% }`, which silently squashes both images to
            the width of their container while leaving the height alone. The
            result is a distorted comparison that still looks plausible. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={sourceUrl}
          alt="Your original image"
          className="absolute left-0 top-0 max-w-none origin-top-left"
          style={{ width: sourceWidth * scale, height: sourceHeight * scale }}
        />
        {/* Traced result, clipped to the slider position. */}
        <div
          className="absolute left-0 top-0 overflow-hidden"
          style={{ width: `${split}%`, height: "100%" }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={tile}
            alt="Vectorized result preview"
            className="absolute left-0 top-0 max-w-none origin-top-left"
            style={{ width: sourceWidth * scale, height: sourceHeight * scale }}
            onLoad={() => setTileLoading(false)}
          />
        </div>

        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Compare original and vectorized"
          aria-valuenow={Math.round(split)}
          aria-valuemin={0}
          aria-valuemax={100}
          tabIndex={0}
          onPointerDown={() => setDragging(true)}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") setSplit((v) => Math.max(0, v - 4));
            if (event.key === "ArrowRight") setSplit((v) => Math.min(100, v + 4));
          }}
          className="absolute top-0 z-10 h-full w-1 cursor-ew-resize bg-blue-600"
          style={{ left: `calc(${split}% - 2px)` }}
        >
          <span className="absolute top-1/2 left-1/2 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
            ⇔
          </span>
        </div>

        {(refining || tileLoading) && (
          <p
            role="status"
            aria-live="polite"
            className="absolute right-3 top-3 z-10 rounded bg-slate-900/80 px-2 py-1 text-xs text-white"
          >
            {refining ? "Refining…" : "Sharpening…"}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label htmlFor="zoom" className="font-medium">
          Zoom
        </label>
        <input
          id="zoom"
          type="range"
          min={MIN_SCALE * 100}
          max={MAX_SCALE * 100}
          step={25}
          value={zoomPercent}
          onChange={(event) => {
            setScale(Number(event.target.value) / 100);
            setTileLoading(true);
          }}
          className="w-48"
        />
        <output className="tabular-nums text-slate-600 dark:text-slate-300">
          {zoomPercent}%
        </output>
        <span className="text-slate-500 dark:text-slate-400">
          Zoom in — the original pixelates, the vector stays sharp.
        </span>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Preview is watermarked. The vector file itself is never sent to your browser
        until you unlock it.
      </p>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { tileUrl } from "@/lib/api";

/**
 * The comparison viewer. This is the product demo, so it gets the detail:
 * drag the handle, scroll or pinch to zoom to 800%, drag the image to pan.
 *
 * Both sides are raster. The left is the user's own file, scaled up by the
 * browser so it pixelates exactly as it will on their machine. The right is
 * a **server-rendered tile** of the trace, because the SVG never reaches the
 * browser before unlock (§7.4) — an <svg> in the DOM is the download,
 * watermark or not.
 *
 * The tile is requested at the current zoom so it is always drawn 1:1. That
 * is the whole point of the control: at 800% the raster is a staircase and
 * the vector is a clean curve. Stretching a stale low-resolution tile makes
 * the vector look *worse* than the raster, so the zoom state is explicit.
 */

const MIN_ZOOM = 1;
const MAX_ZOOM = 8; // the API caps this too; the UI must not promise more
/** How much of the canvas the artwork fills at 100%. */
const IMAGE_WIDTH_RATIO = 0.7;

export type ViewerProps = {
  jobId: string | null;
  sourceUrl: string;
  sourceWidth: number;
  sourceHeight: number;
  height?: number;
  rightLabel?: string;
  /** Stage A → stage B, replaced in place (§7.2). */
  processing?: { label: string; sub: string; progress: number } | null;
};

export default function Viewer({
  jobId,
  sourceUrl,
  sourceWidth,
  sourceHeight,
  height = 480,
  rightLabel = "Vector",
  processing = null,
}: ViewerProps) {
  const viewRef = useRef<HTMLDivElement | null>(null);
  const panRef = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const pinchRef = useRef<{ distance: number; zoom: number } | null>(null);

  const [split, setSplit] = useState(50);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState<"split" | "pan" | null>(null);
  const [tileZoom, setTileZoom] = useState(1);
  const [tileLoading, setTileLoading] = useState(false);
  const [containerWidth, setContainerWidth] = useState(0);

  const clamp = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

  useEffect(() => {
    const element = viewRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setContainerWidth(entry.contentRect.width),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  /**
   * Which tile resolution to ask for.
   *
   * Driven by how many CSS pixels the image actually covers, not by the raw
   * zoom factor. Asking for 8x of a 2000 px canvas would render a 16000 px
   * tile that the browser then throws away, while a 320 px canvas needs
   * every bit of the 8x cap to stay sharp. Discrete powers of two so a wheel
   * gesture queues one render, not one per frame.
   */
  useEffect(() => {
    if (!containerWidth || !sourceWidth) return;
    const displayed = containerWidth * IMAGE_WIDTH_RATIO * zoom;
    const needed = displayed / sourceWidth;
    const step = Math.min(
      MAX_ZOOM,
      Math.max(1, Math.pow(2, Math.ceil(Math.log2(Math.max(needed, 1))))),
    );
    if (step !== tileZoom) {
      setTileZoom(step);
      setTileLoading(true);
    }
  }, [zoom, tileZoom, containerWidth, sourceWidth]);

  const reset = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSplit(50);
  }, []);

  const onWheel = useCallback((event: React.WheelEvent) => {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 0.88 : 1.14;
    setZoom((z) => clamp(z * factor));
  }, []);

  const splitFrom = useCallback((clientX: number) => {
    const box = viewRef.current;
    if (!box) return 50;
    const rect = box.getBoundingClientRect();
    return Math.min(98, Math.max(2, ((clientX - rect.left) / rect.width) * 100));
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const move = (event: PointerEvent) => {
      if (dragging === "split") {
        setSplit(splitFrom(event.clientX));
      } else if (panRef.current) {
        setPan({
          x: panRef.current.px + (event.clientX - panRef.current.x),
          y: panRef.current.py + (event.clientY - panRef.current.y),
        });
      }
    };
    const up = () => setDragging(null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, [dragging, splitFrom]);

  const onTouchStart = (event: React.TouchEvent) => {
    if (event.touches.length === 2) {
      const dx = event.touches[0].clientX - event.touches[1].clientX;
      const dy = event.touches[0].clientY - event.touches[1].clientY;
      pinchRef.current = { distance: Math.hypot(dx, dy), zoom };
    }
  };

  const onTouchMove = (event: React.TouchEvent) => {
    const base = pinchRef.current;
    if (event.touches.length === 2 && base) {
      const dx = event.touches[0].clientX - event.touches[1].clientX;
      const dy = event.touches[0].clientY - event.touches[1].clientY;
      setZoom(clamp((base.zoom * Math.hypot(dx, dy)) / base.distance));
    }
  };

  const onSplitKey = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 10 : 2;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setSplit((v) => Math.max(2, v - step));
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      setSplit((v) => Math.min(98, v + step));
    }
  };

  const tile =
    jobId &&
    tileUrl(jobId, {
      x: 0,
      y: 0,
      w: Math.min(sourceWidth, 2048),
      h: Math.min(sourceHeight, 2048),
      scale: tileZoom,
    });


  return (
    <div>
      <div
        ref={viewRef}
        onPointerDown={(event) => {
          panRef.current = { x: event.clientX, y: event.clientY, px: pan.x, py: pan.y };
          setDragging("pan");
        }}
        onWheel={onWheel}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        style={{
          position: "relative",
          height,
          background: "var(--canvas-bg)",
          overflow: "hidden",
          touchAction: "none",
          cursor: dragging === "pan" ? "grabbing" : "grab",
          userSelect: "none",
        }}
      >
        {/* The original. `image-rendering: pixelated` is deliberate: we are
            showing what their file actually contains, not a smoothed lie. */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={sourceUrl}
            alt="Your original image"
            draggable={false}
            style={{
              maxWidth: "none",
              width: `${IMAGE_WIDTH_RATIO * 100}%`,
              imageRendering: "pixelated",
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            }}
          />
        </div>

        {/* The trace, clipped to the right of the handle. */}
        {tile && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              overflow: "hidden",
              clipPath: `inset(0 0 0 ${split}%)`,
              opacity: processing ? 0 : 1,
              transition: `opacity var(--dur-slow) var(--ease-out)`,
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={tile}
              alt="Vectorized result preview"
              draggable={false}
              onLoad={() => setTileLoading(false)}
              /* Identical box and identical transform to the original: the
                 two halves must be the same size or the comparison is a
                 lie. The tile's extra sharpness comes from its natural
                 resolution, not from being drawn larger. */
              style={{
                maxWidth: "none",
                width: `${IMAGE_WIDTH_RATIO * 100}%`,
                transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              }}
            />
          </div>
        )}

        <span style={labelStyle("left")}>Original</span>
        <span style={labelStyle("right")}>{rightLabel}</span>

        {!processing && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Comparison split, use arrow keys"
            aria-valuenow={Math.round(split)}
            aria-valuemin={0}
            aria-valuemax={100}
            tabIndex={0}
            onKeyDown={onSplitKey}
            onPointerDown={(event) => {
              event.stopPropagation();
              setDragging("split");
            }}
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${split}%`,
              width: 2,
              background: "var(--cyan)",
              cursor: "col-resize",
              touchAction: "none",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%,-50%)",
                width: 40,
                height: 40,
                borderRadius: "var(--radius-full)",
                background: "var(--cyan)",
                boxShadow: "var(--shadow-2)",
                display: "grid",
                placeItems: "center",
                color: "var(--cyan-fg)",
                fontSize: "var(--text-xs)",
                letterSpacing: "0.1em",
              }}
            >
              ◂▸
            </div>
          </div>
        )}

        {processing && (
          <div
            role="status"
            aria-live="polite"
            style={{
              position: "absolute",
              inset: 0,
              display: "grid",
              placeContent: "center",
              gap: 8,
              textAlign: "center",
              color: "#fff",
              background: "rgba(19,25,32,.55)",
              padding: "var(--space-5)",
            }}
          >
            <div style={{ fontWeight: 600 }}>{processing.label}</div>
            <div style={{ fontSize: "var(--text-sm)", opacity: 0.85 }}>{processing.sub}</div>
            <div
              style={{
                width: 220,
                height: 4,
                borderRadius: "var(--radius-full)",
                background: "rgba(255,255,255,.25)",
                overflow: "hidden",
                margin: "0 auto",
              }}
            >
              <div
                style={{
                  width: `${Math.round(processing.progress * 100)}%`,
                  height: "100%",
                  background: "var(--cyan)",
                  transition: `width var(--dur-slow) var(--ease-out)`,
                }}
              />
            </div>
          </div>
        )}

        <div
          style={{
            position: "absolute",
            bottom: 12,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            alignItems: "center",
            gap: 2,
            background: "var(--ink-0)",
            border: "1px solid var(--ink-100)",
            borderRadius: "var(--radius-full)",
            boxShadow: "var(--shadow-2)",
            padding: 3,
          }}
        >
          <button
            type="button"
            aria-label="Zoom out"
            onClick={() => setZoom((z) => clamp(z / 2))}
            style={roundButton}
          >
            −
          </button>
          <span
            style={{
              minWidth: 62,
              textAlign: "center",
              fontSize: "var(--text-sm)",
              fontWeight: 500,
              color: "var(--ink-900)",
            }}
          >
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            aria-label="Zoom in"
            onClick={() => setZoom((z) => clamp(z * 2))}
            style={roundButton}
          >
            +
          </button>
          <span style={{ width: 1, height: 20, background: "var(--ink-100)", margin: "0 4px" }} />
          <button
            type="button"
            onClick={reset}
            style={{ ...roundButton, width: "auto", padding: "0 10px", fontSize: "var(--text-xs)" }}
          >
            Reset
          </button>
        </div>

        {tileLoading && !processing && (
          <span
            role="status"
            aria-live="polite"
            style={{
              position: "absolute",
              top: 10,
              left: "50%",
              transform: "translateX(-50%)",
              background: "rgba(19,25,32,.72)",
              color: "#fff",
              padding: "3px 8px",
              borderRadius: "var(--radius-sm)",
              fontSize: "var(--text-xs)",
            }}
          >
            Sharpening…
          </span>
        )}
      </div>
    </div>
  );
}

const roundButton: React.CSSProperties = {
  width: 32,
  height: 32,
  border: 0,
  background: "transparent",
  borderRadius: "var(--radius-full)",
  cursor: "pointer",
  color: "var(--ink-700)",
  fontSize: "1.1rem",
};

function labelStyle(side: "left" | "right"): React.CSSProperties {
  return {
    position: "absolute",
    top: 10,
    [side]: 10,
    background: "rgba(19,25,32,.72)",
    color: "#fff",
    padding: "3px 8px",
    borderRadius: "var(--radius-sm)",
    fontSize: "var(--text-xs)",
  };
}

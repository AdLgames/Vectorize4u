/**
 * Browser smoke test for the conversion flow.
 *
 * Not a unit test — it drives the real UI against a real API, because the
 * two bugs this caught on its first run were invisible to everything else:
 * a squashed preview image (Tailwind's `img { max-width: 100% }` silently
 * distorting the comparison) and a stale low-resolution tile being stretched
 * on zoom, which made the vector look worse than the raster.
 *
 * Run it against a dev stack:
 *
 *   # terminal 1
 *   VEC_ENVIRONMENT=dev VEC_INLINE_WORKER=1 \
 *     VEC_DATABASE_URL="sqlite+pysqlite:///./dev.db" \
 *     VEC_STORAGE_BACKEND=local uvicorn app.main:app --port 8000
 *   # terminal 2
 *   NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm run dev
 *   # terminal 3
 *   npm install --no-save playwright && node e2e/smoke.mjs
 */

import { chromium } from "playwright";
import path from "node:path";

const WEB = process.env.WEB_BASE ?? "http://127.0.0.1:3000";
const SAMPLE =
  process.env.SAMPLE_IMAGE ??
  path.resolve("../../benchmarks/corpus/logo_flat_small.png");

const failures = [];
function check(name, ok, detail = "") {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures.push(name);
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });

const consoleErrors = [];
page.on("pageerror", (error) => consoleErrors.push(String(error)));

await page.goto(`${WEB}/png-to-svg`, { waitUntil: "networkidle" });
check("landing page renders", (await page.title()).includes("PNG to SVG"));

await page.setInputFiles("input[type=file]", SAMPLE);
await page.waitForSelector("#zoom", { timeout: 120_000 });
check("preview arrives", true);

check(
  "unlock button is offered",
  await page.getByRole("button", { name: /Unlock download/ }).isVisible(),
);

// §7.4: the SVG must never reach the browser before unlock. An <svg> in the
// DOM is the download, watermark or not.
const vectorInDom = await page.evaluate(() =>
  [...document.querySelectorAll("svg")].some((s) => s.querySelectorAll("path").length > 3),
);
check("no traced SVG in the DOM before unlock", vectorInDom === false);

await page.locator("#zoom").fill("800");
await page.waitForFunction(
  () => {
    const img = document.querySelector('img[alt="Vectorized result preview"]');
    return img && img.complete && img.naturalWidth > 1000;
  },
  { timeout: 120_000 },
);

const tile = await page.evaluate(() => {
  const img = document.querySelector('img[alt="Vectorized result preview"]');
  return { natural: img.naturalWidth, css: img.clientWidth };
});
const ratio = tile.natural / tile.css;
check(
  "tile is rendered 1:1 at max zoom",
  Math.abs(ratio - 1) < 0.02,
  `natural ${tile.natural}px vs css ${tile.css}px`,
);

check("no uncaught page errors", consoleErrors.length === 0, consoleErrors.join("; "));

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");

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
await page.waitForSelector("text=Match to your original", { timeout: 120_000 });
check("preview arrives with a score", true);

check(
  "score is shown with its version",
  await page.locator("text=/score s\\d+/").first().isVisible(),
);

check(
  "unlock is offered",
  await page.getByRole("button", { name: /1 credit/ }).isVisible(),
);

// §7.4: the SVG must never reach the browser before unlock. An <svg> in the
// DOM is the download, watermark or not.
const vectorInDom = await page.evaluate(() =>
  [...document.querySelectorAll("svg")].some((s) => s.querySelectorAll("path").length > 3),
);
check("no traced SVG in the DOM before unlock", vectorInDom === false);

// Zoom to the maximum the UI offers and confirm the tile is drawn 1:1.
// A stale low-resolution tile stretched by the browser makes the vector look
// worse than the raster, which is the opposite of the point.
for (let i = 0; i < 3; i++) {
  await page.getByRole("button", { name: "Zoom in" }).click();
}
await page.waitForFunction(
  () => {
    const img = document.querySelector('img[alt="Vectorized result preview"]');
    return img && img.complete && img.naturalWidth > 600;
  },
  { timeout: 120_000 },
);
await page.waitForTimeout(300);

const pair = await page.evaluate(() => {
  const vector = document.querySelector('img[alt="Vectorized result preview"]');
  const raster = document.querySelector('img[alt="Your original image"]');
  const box = (el) => el.getBoundingClientRect();
  return {
    vectorNatural: vector.naturalWidth,
    rasterNatural: raster.naturalWidth,
    vectorCss: box(vector).width,
    rasterCss: box(raster).width,
  };
});

// Both halves must be drawn at the same size, or the comparison is a lie.
check(
  "both halves are drawn at the same size",
  Math.abs(pair.vectorCss - pair.rasterCss) < 2,
  `vector ${Math.round(pair.vectorCss)}px vs raster ${Math.round(pair.rasterCss)}px`,
);

// And the vector side must actually carry more pixels — that IS the pitch.
check(
  "the vector tile is far denser than the original",
  pair.vectorNatural >= pair.rasterNatural * 4,
  `${pair.vectorNatural}px vs ${pair.rasterNatural}px source`,
);

// The dark theme is a token swap, so one toggle must repaint everything.
await page.getByRole("button", { name: /Dark|Light/ }).click();
await page.waitForTimeout(200);
check(
  "theme toggle switches the token set",
  (await page.evaluate(() => document.documentElement.getAttribute("data-theme"))) !== null,
);

check("no uncaught page errors", consoleErrors.length === 0, consoleErrors.join("; "));

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");

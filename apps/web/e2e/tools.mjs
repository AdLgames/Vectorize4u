/**
 * The free tools run entirely in the browser, so there is no server test
 * that can cover them — this is the only place their logic is exercised.
 *
 *   WEB_BASE=http://127.0.0.1:3100 node e2e/tools.mjs
 */

import { chromium } from "playwright";
import path from "node:path";

const WEB = process.env.WEB_BASE ?? "http://127.0.0.1:3000";
const SAMPLE =
  process.env.SAMPLE_IMAGE ?? path.resolve("../../benchmarks/corpus/logo_flat_small.png");

const failures = [];
function check(name, ok, detail = "") {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures.push(name);
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(String(error)));

// --- minifier ----------------------------------------------------------
await page.goto(`${WEB}/tools/svg-minifier`, { waitUntil: "networkidle" });
const summary = await page.locator("text=/\\d+ B → \\d+ B|\\d+ B → [\\d.]+ kB/").first().innerText();
check("minifier reports a size change", /→/.test(summary), summary);

const savedPercent = Number((await page.locator("text=smaller").locator("xpath=preceding-sibling::div").first().innerText()).replace("%", ""));
check("the sample gets meaningfully smaller", savedPercent >= 20, `${savedPercent}%`);

// The after pane must still render the same shape: a path element survives.
const afterPaths = await page.locator('[data-pane="after"] svg path').count();
check("the minified SVG still draws its path", afterPaths >= 1);

// Rounding is visible and reversible.
await page.locator('input[type="range"]').first().fill("0");
const rounded = await page.locator('[data-pane="after"] svg path').first().getAttribute("d");
check("precision 0 rounds the coordinates", !/\./.test(rounded ?? "."), rounded ?? "");

// Garbage in gets an error, not a crash.
await page.locator("textarea").fill("not an svg at all");
check("invalid input is refused", await page.getByText("That is not valid SVG").isVisible());

// --- svg to png --------------------------------------------------------
await page.goto(`${WEB}/tools/svg-to-png`, { waitUntil: "networkidle" });
await page.waitForSelector('img[alt="PNG preview"]');
const src = await page.getAttribute('img[alt="PNG preview"]', "src");
check("a PNG data URL is produced", (src ?? "").startsWith("data:image/png;base64,"));
const dims = await page.locator("text=/\\d+ × \\d+ px/").first().innerText();
check("the output size is reported", /1024 × \d+ px/.test(dims), dims);

// --- palette -----------------------------------------------------------
await page.goto(`${WEB}/tools/palette-extractor`, { waitUntil: "networkidle" });
await page.setInputFiles("input[type=file]", SAMPLE);
await page.waitForSelector("text=/% of the image/", { timeout: 15_000 });
const swatches = await page.locator("code").count();
check("swatches are extracted", swatches >= 2, `${swatches} swatches`);
const hex = await page.locator("code").first().innerText();
check("swatches are hex values", /^#[0-9a-f]{6}$/.test(hex), hex);
const shares = await page.locator("text=/% of the image/").allInnerTexts();
const total = shares.reduce((sum, text) => sum + Number(text.match(/([\d.]+)%/)[1]), 0);
check("the shares add up to the whole image", Math.abs(total - 100) < 1.5, `${total.toFixed(1)}%`);

check("no uncaught page errors", errors.length === 0, errors.join(" | "));

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} failed: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

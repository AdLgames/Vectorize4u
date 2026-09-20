/**
 * Every intent page has to convert, not just render.
 *
 * The pages set their own defaults — a tighter palette for logos, heavy
 * despeckling and no background for embroidery, DXF and a mandatory size
 * for cutting — and a default that the API rejects would break the page
 * for everyone while looking fine in a build.
 *
 *   WEB_BASE=http://127.0.0.1:3100 node e2e/intent-pages.mjs
 */

import { chromium } from "playwright";
import path from "node:path";

const WEB = process.env.WEB_BASE ?? "http://127.0.0.1:3000";
const SAMPLE =
  process.env.SAMPLE_IMAGE ?? path.resolve("../../benchmarks/corpus/logo_flat_small.png");

const PAGES = [
  { slug: "jpg-to-svg", title: "JPG to SVG" },
  { slug: "logo-to-vector", title: "Logo to vector" },
  { slug: "image-to-dxf", title: "Image to DXF" },
  { slug: "vector-art-for-embroidery-digitizing", title: "embroidery" },
];

const failures = [];
function check(name, ok, detail = "") {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures.push(name);
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

for (const target of PAGES) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));

  await page.goto(`${WEB}/${target.slug}`, { waitUntil: "networkidle" });
  check(`${target.slug}: renders`, (await page.title()).includes(target.title));

  await page.setInputFiles("input[type=file]", SAMPLE);
  const traced = await page
    .waitForSelector("text=Match to your original", { timeout: 120_000 })
    .then(() => true)
    .catch(() => false);
  check(`${target.slug}: converts with its own defaults`, traced);

  check(`${target.slug}: no vector in the DOM before unlock`, !(await page.content()).includes("<path"));
  check(`${target.slug}: no uncaught errors`, errors.length === 0, errors.join(" | "));
  await page.close();
}

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} failed: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nall checks passed");

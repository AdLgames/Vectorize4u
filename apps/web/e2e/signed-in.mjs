/**
 * The signed-in flow, end to end: sign in, convert, unlock, download.
 *
 * This is the path that takes money, and until it ran in a browser the
 * token was a placeholder in three separate components. Run it against a
 * dev stack (see docs/runbook.md); with a real Supabase project the magic
 * link cannot be clicked by a script, which is exactly why the dev mode
 * exists.
 */

import { chromium } from "playwright";
import path from "node:path";

const WEB = process.env.WEB_BASE ?? "http://127.0.0.1:3000";
const SAMPLE =
  process.env.SAMPLE_IMAGE ?? path.resolve("../../benchmarks/corpus/logo_flat_small.png");
const EMAIL = process.env.TEST_EMAIL ?? `buyer-${Date.now()}@studio.test`;

const failures = [];
function check(name, ok, detail = "") {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures.push(name);
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error)));

// --- signed out ---------------------------------------------------------
await page.goto(`${WEB}/account`, { waitUntil: "networkidle" });
check(
  "the account page asks you to sign in",
  await page.getByRole("button", { name: /Sign in/i }).first().isVisible(),
);

// --- sign in ------------------------------------------------------------
await page.fill("#signin-email", EMAIL);
await page.getByRole("button", { name: /Sign in \(dev\)|Email me a link/ }).click();
await page.waitForSelector("text=Downloads this month", { timeout: 30_000 });
check("signing in loads the account", true);

const credits = await page.evaluate(() => {
  const match = document.body.innerText.match(/(\d+)\s+credits?/);
  return match ? Number(match[1]) : null;
});
check("the header shows a credit balance", credits !== null, `${credits} credits`);

// --- convert ------------------------------------------------------------
await page.goto(`${WEB}/convert`, { waitUntil: "networkidle" });
await page.setInputFiles("input[type=file]", SAMPLE);
await page.waitForSelector("text=Match to your original", { timeout: 120_000 });
check("the preview arrives while signed in", true);

const lockedOutputs = await page.getByRole("link", { name: /Download \./ }).count();
check("no download links before unlock", lockedOutputs === 0);

// --- unlock -------------------------------------------------------------
await page.getByRole("button", { name: /1 credit/ }).click();
await page.waitForSelector("a:has-text('Download .svg')", { timeout: 60_000 });
check("unlocking reveals the real files", true);

const href = await page.getByRole("link", { name: "Download .svg" }).getAttribute("href");
const svg = await page.request.get(href);
const body = await svg.text();
check("the downloaded SVG is real vector output", body.startsWith("<svg"), `${body.length} bytes`);
check("it carries a physical size", /width="[\d.]+mm"/.test(body));

const after = await page.evaluate(() => {
  const match = document.body.innerText.match(/(\d+)\s+credits?/);
  return match ? Number(match[1]) : null;
});
check("a credit was spent", after === credits - 1, `${credits} → ${after}`);

// --- the session survives a reload --------------------------------------
await page.reload({ waitUntil: "networkidle" });
await page.goto(`${WEB}/account`, { waitUntil: "networkidle" });
await page.waitForSelector("text=Downloads this month", { timeout: 30_000 });
check("the session survives a reload", true);

// --- sign out -----------------------------------------------------------
await page.getByRole("button", { name: /Sign out/ }).click();
await page.waitForSelector("#signin-email", { timeout: 30_000 });
check("signing out returns to the sign-in form", true);

check("no uncaught page errors", pageErrors.length === 0, pageErrors.join("; "));

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");

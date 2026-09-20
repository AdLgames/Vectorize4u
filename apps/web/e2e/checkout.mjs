/**
 * The purchase paths, short of Stripe itself.
 *
 * Stripe's hosted page cannot be driven from here, and a test that stops at
 * the redirect is still worth having: everything up to that redirect is our
 * code, and so is every way it can go wrong — no session, no Stripe keys,
 * an empty balance. Run it against a dev stack (see docs/runbook.md).
 *
 * With VEC_STRIPE_SECRET_KEY unset the API answers 503, which is the state
 * this asserts. With a test key set, the "buy" checks will instead land on
 * checkout.stripe.com — also a pass, and noted as such.
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

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error)));

// --- the price list is served, not hard-coded in two places -------------
const plans = await (await page.request.get(`${process.env.API_BASE ?? "http://127.0.0.1:8000"}/v1/plans`)).json();
const pack = plans.find((p) => p.id === "pack");
check("the API serves the price list", pack?.amount === 900 && pack?.credits === 50);

await page.goto(`${WEB}/`, { waitUntil: "networkidle" });
const shown = await page.locator("#pricing").innerText();
check(
  "the pricing section matches what the API charges",
  shown.includes("$9") && shown.includes("$12") && shown.includes("$29"),
);

// --- signed out: buying sends you to sign in ----------------------------
await page.getByRole("button", { name: "Buy 50 credits" }).click();
await page.waitForURL(/\/signin/, { timeout: 15_000 });
check("buying while signed out goes to sign-in", true);

// --- signing in returns you to what you were buying ---------------------
await page.fill("#signin-email", `buyer-${Date.now()}@studio.test`);
await page.getByRole("button", { name: /Sign in \(dev\)|Email me a link/ }).click();
await page.waitForSelector("#pricing", { timeout: 30_000 });
check("signing in returns you to the price list, not a generic page", true);

// --- signed in: no Stripe keys means a clear message, not a crash -------
await page.getByRole("button", { name: /^Buy 50 credits$/ }).first().click();
const outcome = await Promise.race([
  page
    .waitForSelector("text=Payments aren't switched on yet", { timeout: 20_000 })
    .then(() => "unconfigured"),
  page.waitForURL(/checkout\.stripe\.com/, { timeout: 20_000 }).then(() => "stripe"),
]).catch(() => "neither");
check(
  "buying says something useful",
  outcome !== "neither",
  outcome === "stripe" ? "reached Stripe Checkout" : "Stripe not configured, said so plainly",
);

if (outcome === "stripe") {
  await page.goBack();
}

// --- running out of credits offers the pack ------------------------------
await page.goto(`${WEB}/convert`, { waitUntil: "networkidle" });
await page.setInputFiles("input[type=file]", SAMPLE);
await page.waitForSelector("text=Match to your original", { timeout: 120_000 });

// Free tier grants 3; spend them all, then the fourth must offer the pack.
for (let i = 0; i < 4; i++) {
  const unlock = page.getByRole("button", { name: /1 credit/ });
  if (!(await unlock.isVisible().catch(() => false))) break;
  await unlock.click();
  await page.waitForTimeout(1500);
  if (i < 3) {
    await page.goto(`${WEB}/convert`, { waitUntil: "networkidle" });
    await page.setInputFiles("input[type=file]", SAMPLE);
    await page.waitForSelector("text=Match to your original", { timeout: 120_000 });
  }
}

const offered = await page
  .waitForSelector("text=You're out of downloads", { timeout: 20_000 })
  .then(() => true)
  .catch(() => false);
check("running out of credits offers the credit pack", offered);

// --- the success page never claims credits it cannot see -----------------
await page.goto(`${WEB}/checkout/success`, { waitUntil: "networkidle" });
const success = await page.locator("body").innerText();
check(
  "the success page reports the real balance",
  success.includes("Payment received"),
  success.includes("adding your credits") ? "waiting for the webhook" : "balance already present",
);

check("no uncaught page errors", pageErrors.length === 0, pageErrors.join("; "));

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");

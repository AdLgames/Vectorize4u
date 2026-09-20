/**
 * Guards the intent pages against becoming doorway pages (§9).
 *
 * "Each needs genuinely different copy" is a requirement, not a style note:
 * a set of near-identical pages with the keyword swapped is the pattern
 * search engines demote, and it converts nobody either. Judging that by eye
 * works until page six, so it is measured here instead.
 *
 * Checks, per page: it is in the sitemap, it has its own canonical, title
 * and description, it carries real copy, and it does not overlap another
 * page's copy beyond a threshold.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const APP = new URL("../app", import.meta.url).pathname;

// The pages §9 names, plus the two that shipped in Phase 3.
const INTENT_PAGES = [
  "png-to-svg",
  "jpg-to-svg",
  "logo-to-vector",
  "image-to-dxf",
  "convert-for-cricut",
  "vector-art-for-embroidery-digitizing",
];

const MIN_WORDS = 400;
const MAX_OVERLAP = 0.25;

const failures = [];
const fail = (message) => failures.push(message);

const sitemap = readFileSync(join(APP, "sitemap.ts"), "utf8");

/** The prose a reader actually sees: string literals, minus code noise. */
function copyOf(source) {
  const withoutImports = source.replace(/^import[\s\S]*?;$/gm, "");
  const strings = withoutImports.match(/"[^"\n]{25,}"|`[^`]{25,}`|>[^<>{}]{25,}</g) ?? [];
  return strings
    .join(" ")
    .replace(/[`"<>]/g, " ")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

function shingles(text) {
  const words = text.split(" ").filter(Boolean);
  const set = new Set();
  for (let i = 0; i + 4 < words.length; i += 1) set.add(words.slice(i, i + 5).join(" "));
  return set;
}

function overlap(a, b) {
  if (!a.size || !b.size) return 0;
  let shared = 0;
  for (const item of a) if (b.has(item)) shared += 1;
  return shared / Math.min(a.size, b.size);
}

const pages = new Map();
const canonicals = new Map();
const titles = new Map();
const descriptions = new Map();

for (const slug of INTENT_PAGES) {
  let source;
  try {
    source = readFileSync(join(APP, slug, "page.tsx"), "utf8");
  } catch {
    fail(`${slug}: no page.tsx`);
    continue;
  }

  if (!sitemap.includes(`/${slug}\``)) fail(`${slug}: missing from sitemap.ts`);

  const canonical = source.match(/canonical:\s*"([^"]+)"/)?.[1];
  if (canonical !== `/${slug}`) fail(`${slug}: canonical is ${canonical ?? "unset"}`);
  if (canonicals.has(canonical)) fail(`${slug}: shares a canonical with ${canonicals.get(canonical)}`);
  canonicals.set(canonical, slug);

  const title = source.match(/title:\s*"([^"]+)"/)?.[1];
  if (!title) fail(`${slug}: no title`);
  else if (titles.has(title)) fail(`${slug}: shares its title with ${titles.get(title)}`);
  else titles.set(title, slug);

  const description = source.match(/description:\s*\n?\s*"([^"]+)"/)?.[1];
  if (!description) fail(`${slug}: no meta description`);
  else if (descriptions.has(description))
    fail(`${slug}: shares its description with ${descriptions.get(description)}`);
  else descriptions.set(description, slug);

  const copy = copyOf(source);
  const words = copy.split(" ").filter(Boolean).length;
  if (words < MIN_WORDS) fail(`${slug}: ${words} words of copy, want at least ${MIN_WORDS}`);

  if (!/faq|Faq/.test(source)) fail(`${slug}: no FAQ block (the FAQPage JSON-LD needs one)`);

  pages.set(slug, shingles(copy));
}

const slugs = [...pages.keys()];
for (let i = 0; i < slugs.length; i += 1) {
  for (let j = i + 1; j < slugs.length; j += 1) {
    const score = overlap(pages.get(slugs[i]), pages.get(slugs[j]));
    if (score > MAX_OVERLAP) {
      fail(
        `${slugs[i]} and ${slugs[j]} share ${(score * 100).toFixed(0)}% of their copy ` +
          `(limit ${MAX_OVERLAP * 100}%) — that is a doorway page, not an intent page`,
      );
    }
  }
}

// Every page under app/ that is publicly indexable should be in the sitemap.
const routes = readdirSync(APP, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && !entry.name.startsWith("_"))
  .map((entry) => entry.name);
const PRIVATE = new Set(["auth", "signin", "account", "checkout", "convert"]);
for (const route of routes) {
  if (PRIVATE.has(route)) continue;
  if (!sitemap.includes(`/${route}\``)) fail(`/${route} is public but not in sitemap.ts`);
}

if (failures.length) {
  console.error("SEO page checks failed:\n" + failures.map((f) => `  - ${f}`).join("\n"));
  process.exit(1);
}
console.log(`SEO page checks passed for ${slugs.length} intent pages.`);

/**
 * Tokens that are too light to carry text must not carry text.
 *
 * This has now been fixed three times: `--ink-400` is 3.61:1 on white and
 * `--cyan` is 4.13:1, both below the 4.5:1 that WCAG AA asks of normal
 * text, and both perfectly correct for the borders, rules and fills they
 * also serve. So the rule is mechanical — those tokens may appear
 * anywhere except after `color:` — and it is checked rather than
 * remembered.
 *
 * The thresholds are computed from globals.css rather than hard-coded, so
 * changing a token's value re-classifies it automatically.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const WEB = new URL("..", import.meta.url).pathname;
const MIN_CONTRAST = 4.5;

function luminance(hex) {
  const parts = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = parts.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

/** Light-mode token values, which is the half of the palette on white. */
function tokens() {
  const css = readFileSync(join(WEB, "app/globals.css"), "utf8");
  const light = css.split('[data-theme="dark"]')[0];
  const found = new Map();
  for (const [, name, value] of light.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    if (!found.has(name)) found.set(name, value);
  }
  return found;
}

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...walk(path));
    else if (path.endsWith(".tsx") || path.endsWith(".ts")) out.push(path);
  }
  return out;
}

const palette = tokens();
const background = palette.get("ink-0") ?? "#ffffff";
const unsafe = new Set();
for (const [name, value] of palette) {
  if (name.startsWith("ink-") || ["cyan", "magenta", "green", "amber"].includes(name)) {
    if (contrast(value, background) < MIN_CONTRAST) unsafe.add(`--${name}`);
  }
}

const failures = [];
for (const file of [...walk(join(WEB, "app")), ...walk(join(WEB, "components"))]) {
  const source = readFileSync(file, "utf8");
  source.split("\n").forEach((line, index) => {
    // `color:` only. The same token behind a border or a background is
    // fine, and banning it outright would just move the problem.
    const match = line.match(/\bcolor:\s*(?:[^,;}]*?)var\((--[\w-]+)\)/);
    if (match && unsafe.has(match[1])) {
      failures.push(
        `${file.replace(WEB, "")}:${index + 1}  ${match[1]} is ` +
          `${contrast(palette.get(match[1].slice(2)), background).toFixed(2)}:1 on the page ` +
          `background — too light for text`,
      );
    }
  });
}

if (failures.length) {
  console.error(
    `Text in a colour below ${MIN_CONTRAST}:1:\n` + failures.map((f) => `  - ${f}`).join("\n"),
  );
  process.exit(1);
}
console.log(
  `Contrast check passed. Too light for text, and correctly unused there: ` +
    `${[...unsafe].join(", ")}`,
);

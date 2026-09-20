/**
 * A small, conservative SVG minifier that runs in the browser.
 *
 * Conservative on purpose: this is a free tool people paste production
 * artwork into, and a minifier that silently changes how a file renders is
 * worse than no minifier. So it only removes things that cannot affect
 * rendering, and rounds numbers to a precision the caller chooses and can
 * see the result of.
 */

export type MinifyOptions = {
  /** Decimal places kept on path and geometry numbers. */
  precision: number;
  /** Drop `id` attributes nothing references. */
  dropUnusedIds: boolean;
  /** Drop editor namespaces (Inkscape, Illustrator, Sketch metadata). */
  dropEditorData: boolean;
};

export type MinifyResult = {
  svg: string;
  before: number;
  after: number;
  removed: string[];
};

const EDITOR_PREFIXES = ["inkscape", "sodipodi", "sketch", "illustrator", "adobe", "figma"];
const DROP_ELEMENTS = ["metadata", "desc", "title"];

/** Round every number in a string of path/geometry data. */
function roundNumbers(value: string, precision: number): string {
  return value.replace(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi, (match) => {
    const n = Number(match);
    if (!Number.isFinite(n)) return match;
    const rounded = Number(n.toFixed(precision));
    return String(rounded);
  });
}

const GEOMETRY_ATTRS = new Set([
  "d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
  "width", "height", "transform", "viewBox", "stroke-width", "offset",
]);

export function minifySvg(source: string, options: MinifyOptions): MinifyResult {
  const before = new Blob([source]).size;
  const removed: string[] = [];

  const parsed = new DOMParser().parseFromString(source, "image/svg+xml");
  const failure = parsed.querySelector("parsererror");
  if (failure || !parsed.documentElement || parsed.documentElement.nodeName === "html") {
    throw new Error("that does not parse as SVG");
  }

  const root = parsed.documentElement;
  const referenced = new Set<string>();
  for (const match of source.matchAll(/(?:url\(#|href="#|xlink:href="#)([^)"]+)/g)) {
    referenced.add(match[1]);
  }

  const walk = (node: Element) => {
    for (const child of [...node.children]) walk(child);

    const name = node.nodeName.toLowerCase();
    if (DROP_ELEMENTS.includes(name)) {
      // <title> and <desc> are accessibility features on the root element,
      // so only nested decorative ones go.
      if (name === "metadata" || node.parentElement !== node.ownerDocument.documentElement) {
        node.remove();
        removed.push(`<${name}>`);
        return;
      }
    }
    if (options.dropEditorData && EDITOR_PREFIXES.some((p) => name.startsWith(`${p}:`))) {
      node.remove();
      removed.push(`<${name}>`);
      return;
    }
    // An empty group renders nothing and is pure weight.
    if (name === "g" && node.children.length === 0 && !node.textContent?.trim()) {
      node.remove();
      removed.push("empty <g>");
      return;
    }

    for (const attr of [...node.attributes]) {
      const attrName = attr.name.toLowerCase();

      if (options.dropEditorData && EDITOR_PREFIXES.some((p) => attrName.startsWith(`${p}:`))) {
        node.removeAttribute(attr.name);
        removed.push(attr.name);
        continue;
      }
      if (options.dropUnusedIds && attrName === "id" && !referenced.has(attr.value)) {
        node.removeAttribute(attr.name);
        removed.push("unused id");
        continue;
      }
      if (attrName === "style" && attr.value.trim() === "") {
        node.removeAttribute(attr.name);
        continue;
      }
      if (GEOMETRY_ATTRS.has(attrName)) {
        const rounded = roundNumbers(attr.value, options.precision).replace(/\s+/g, " ").trim();
        if (rounded !== attr.value) node.setAttribute(attr.name, rounded);
      }
    }
  };

  walk(root);

  // Comments carry no rendering meaning.
  const iterator = parsed.createNodeIterator(parsed, NodeFilter.SHOW_COMMENT);
  const comments: Node[] = [];
  let current = iterator.nextNode();
  while (current) {
    comments.push(current);
    current = iterator.nextNode();
  }
  for (const comment of comments) comment.parentNode?.removeChild(comment);
  if (comments.length) removed.push(`${comments.length} comment${comments.length > 1 ? "s" : ""}`);

  const svg = new XMLSerializer()
    .serializeToString(parsed)
    .replace(/>\s+</g, "><")
    .replace(/\s{2,}/g, " ")
    .trim();

  return { svg, before, after: new Blob([svg]).size, removed: [...new Set(removed)] };
}

import Link from "next/link";

/**
 * The footer carries the internal links to every intent page (§9).
 *
 * Not decoration: a page nothing links to is a page that takes far longer
 * to be found, and these are the pages the business is built on ranking
 * for. One place, so a new page is linked everywhere the moment it exists.
 */

export const CONVERSION_PAGES = [
  { href: "/png-to-svg", label: "PNG to SVG" },
  { href: "/jpg-to-svg", label: "JPG to SVG" },
  { href: "/logo-to-vector", label: "Logo to vector" },
  { href: "/image-to-dxf", label: "Image to DXF" },
  { href: "/convert-for-cricut", label: "Convert for Cricut" },
  { href: "/vector-art-for-embroidery-digitizing", label: "Art for embroidery" },
];

const OTHER = [
  { href: "/batch", label: "Batch conversion" },
  { href: "/api", label: "API docs" },
  { href: "/account", label: "Account" },
];

const TOOLS = [
  { href: "/tools/svg-minifier", label: "SVG minifier" },
  { href: "/tools/svg-to-png", label: "SVG to PNG" },
  { href: "/tools/palette-extractor", label: "Palette extractor" },
];

const columnStyle: React.CSSProperties = {
  display: "grid",
  gap: 8,
  alignContent: "start",
};

const headingStyle: React.CSSProperties = {
  fontSize: "var(--text-xs)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: "var(--ink-500)",
  margin: 0,
};

const linkStyle: React.CSSProperties = {
  fontSize: "var(--text-sm)",
  color: "var(--ink-700)",
  textDecoration: "none",
};

export default function SiteFooter() {
  return (
    <footer
      style={{
        maxWidth: 1200,
        margin: "0 auto",
        padding: "var(--space-6) 20px var(--space-8)",
        display: "grid",
        gap: "var(--space-6)",
      }}
    >
      <nav
        aria-label="Footer"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "var(--space-5)",
        }}
      >
        <div style={columnStyle}>
          <h2 style={headingStyle}>Convert</h2>
          {CONVERSION_PAGES.map((page) => (
            <Link key={page.href} href={page.href} style={linkStyle}>
              {page.label}
            </Link>
          ))}
        </div>
        <div style={columnStyle}>
          <h2 style={headingStyle}>Free tools</h2>
          {TOOLS.map((page) => (
            <Link key={page.href} href={page.href} style={linkStyle}>
              {page.label}
            </Link>
          ))}
        </div>
        <div style={columnStyle}>
          <h2 style={headingStyle}>Product</h2>
          {OTHER.map((page) => (
            <Link key={page.href} href={page.href} style={linkStyle}>
              {page.label}
            </Link>
          ))}
        </div>
      </nav>

      <div
        style={{
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
          fontSize: "var(--text-xs)",
          color: "var(--ink-500)",
          borderTop: "1px solid var(--ink-100)",
          paddingTop: "var(--space-4)",
        }}
      >
        <span>© 2026 Vectorize4u</span>
        <span>
          We delete your files after 24 hours on free, 30 days on paid plans. They are never
          used to train anything.
        </span>
      </div>
    </footer>
  );
}

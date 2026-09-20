import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "https://vectorize.example";

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: {
    default: "Vectorize — batch raster to vector, at the right size",
    template: "%s | Vectorize",
  },
  description:
    "Convert PNG and JPEG logos to clean SVG, DXF, PDF and EPS. Built for people who vectorize for money: batch conversion, cutter-safe paths and an honest quality score.",
  openGraph: {
    type: "website",
    siteName: "Vectorize",
    images: ["/og.svg"],
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-blue-600 focus:px-4 focus:py-2 focus:text-white"
        >
          Skip to content
        </a>
        <header className="border-b border-slate-200 dark:border-slate-800">
          <nav
            aria-label="Main"
            className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-4 text-sm"
          >
            <Link href="/" className="font-semibold tracking-tight">
              Vectorize
            </Link>
            <Link href="/convert" className="text-slate-600 hover:underline dark:text-slate-300">
              Convert
            </Link>
            <Link href="/batch" className="text-slate-600 hover:underline dark:text-slate-300">
              Batch
            </Link>
            <Link
              href="/convert-for-cricut"
              className="text-slate-600 hover:underline dark:text-slate-300"
            >
              For Cricut
            </Link>
            <Link
              href="/account"
              className="ml-auto text-slate-600 hover:underline dark:text-slate-300"
            >
              Account
            </Link>
          </nav>
        </header>
        <main id="main">{children}</main>
        <footer className="mt-16 border-t border-slate-200 px-4 py-10 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <div className="mx-auto max-w-6xl space-y-2">
            <p>
              Free previews are rate-limited for normal human use. Files are deleted
              automatically: 24 hours on the free tier, 30 days on paid plans.
            </p>
            <p>
              We store statistics about your images — never the pixels — after deletion, to
              improve results.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}

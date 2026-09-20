import type { Metadata } from "next";
import { Instrument_Sans } from "next/font/google";
import AuthProvider from "@/components/AuthProvider";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "https://vectorize4u.example";

const sans = Instrument_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: {
    default: "Vectorize4u — turn a rough image into a file that prints and cuts clean",
    template: "%s | Vectorize4u",
  },
  description:
    "Convert PNG and JPEG artwork to clean SVG, PDF, EPS and DXF. Batch up to 500 files, set the exact size it should cut at, and see a quality score before you pay.",
  alternates: { canonical: "/" },
  openGraph: { type: "website", siteName: "Vectorize4u", images: ["/og.svg"] },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable}>
      <head>
        {/* Applied before first paint so a dark-theme visitor never sees a
            white flash. Inline by necessity: any external script is already
            too late. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('v4u.theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}`,
          }}
        />
      </head>
      <body style={{ fontFamily: "var(--font-sans), ui-sans-serif, system-ui, sans-serif" }}>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <AuthProvider>
          <SiteHeader />
          <main
          id="main"
          style={{
            maxWidth: 1200,
            margin: "0 auto",
            borderLeft: "1px solid var(--ink-100)",
            borderRight: "1px solid var(--ink-100)",
            background: "var(--ink-0)",
            minHeight: "80vh",
          }}
        >
            {children}
          </main>
        </AuthProvider>
        <SiteFooter />
      </body>
    </html>
  );
}

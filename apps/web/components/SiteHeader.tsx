"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import Brand from "./Brand";
import { useAuth } from "./AuthProvider";
import { applyTheme, currentTheme, type Theme } from "@/lib/theme";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/convert", label: "Convert" },
  { href: "/batch", label: "Batch" },
  { href: "/account", label: "Account" },
];

export default function SiteHeader() {
  const pathname = usePathname();
  const { email, signedIn, credits } = useAuth();
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => setTheme(currentTheme()), []);

  const toggle = () => {
    const next: Theme = theme === "light" ? "dark" : "light";
    applyTheme(next);
    setTheme(next);
  };

  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: 20,
        padding: "14px 20px",
        borderBottom: "1px solid var(--ink-100)",
        position: "sticky",
        top: 0,
        background: "var(--ink-0)",
        zIndex: 30,
        flexWrap: "wrap",
      }}
    >
      <Link
        href="/"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          textDecoration: "none",
          color: "var(--ink-900)",
        }}
      >
        <Brand />
        <span style={{ fontWeight: 600, letterSpacing: "-0.01em" }}>Vectorize4u</span>
      </Link>

      <nav aria-label="Main" style={{ display: "flex", gap: 16, fontSize: "var(--text-sm)", flexWrap: "wrap" }}>
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              style={{
                textDecoration: "none",
                padding: "2px 0",
                color: active ? "var(--ink-900)" : "var(--ink-500)",
                fontWeight: active ? 500 : 400,
                borderBottom: `2px solid ${active ? "var(--cyan)" : "transparent"}`,
              }}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div
        style={{
          marginLeft: "auto",
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontSize: "var(--text-sm)",
        }}
      >
        {signedIn ? (
          <>
            {credits !== null && (
              <span style={{ color: "var(--ink-500)" }}>
                {credits} {credits === 1 ? "credit" : "credits"}
              </span>
            )}
            <span
              aria-label={email ?? "Signed in"}
              title={email ?? undefined}
              style={{
                width: 26,
                height: 26,
                borderRadius: "var(--radius-full)",
                background: "var(--cyan-soft)",
                color: "var(--cyan)",
                display: "grid",
                placeItems: "center",
                fontSize: "var(--text-xs)",
                fontWeight: 600,
                textTransform: "uppercase",
              }}
            >
              {(email ?? "?").slice(0, 2)}
            </span>
          </>
        ) : (
          <Link
            href="/signin"
            style={{ color: "var(--ink-500)", textDecoration: "none" }}
          >
            Sign in
          </Link>
        )}
        <button
          type="button"
          onClick={toggle}
          style={{
            border: "1px solid var(--ink-200)",
            background: "transparent",
            color: "var(--ink-500)",
            padding: "4px 10px",
            borderRadius: "var(--radius-sm)",
            fontSize: "var(--text-xs)",
            cursor: "pointer",
          }}
        >
          {theme === "light" ? "Dark" : "Light"}
        </button>
      </div>
    </header>
  );
}

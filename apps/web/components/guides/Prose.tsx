import type { ReactNode } from "react";

/**
 * Shared shell for the tutorials (§9). Layout only — every word of the
 * copy lives in its own page, because a tutorial assembled from shared
 * boilerplate is the same doorway-page problem in a longer form.
 */

export function GuideHeader({
  title,
  standfirst,
  minutes,
}: {
  title: string;
  standfirst: string;
  minutes: number;
}) {
  return (
    <header style={{ maxWidth: "62ch", display: "grid", gap: "var(--space-3)" }}>
      <p
        style={{
          fontSize: "var(--text-xs)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--ink-500)",
          margin: 0,
        }}
      >
        Guide · {minutes} min read
      </p>
      <h1 style={{ fontSize: "var(--text-h1)", margin: 0 }}>{title}</h1>
      <p style={{ fontSize: "var(--text-lg)", color: "var(--ink-500)", margin: 0 }}>{standfirst}</p>
    </header>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ maxWidth: "68ch", display: "grid", gap: "var(--space-3)" }}>
      <h2 style={{ fontSize: "var(--text-h2)", margin: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

export function P({ children }: { children: ReactNode }) {
  return <p style={{ color: "var(--ink-500)", margin: 0 }}>{children}</p>;
}

export function Steps({ children }: { children: ReactNode }) {
  return (
    <ol style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 10 }}>
      {children}
    </ol>
  );
}

export function Bullets({ children }: { children: ReactNode }) {
  return (
    <ul style={{ color: "var(--ink-500)", margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}>
      {children}
    </ul>
  );
}

export function GuideLayout({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: "40px 20px 72px", display: "grid", gap: "var(--space-6)" }}>
      {children}
    </div>
  );
}

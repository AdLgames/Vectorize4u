/**
 * The primitives the prototype's screens are built from.
 *
 * Everything reads a design token — no literal colours below this file —
 * so the dark theme stays a token swap rather than a second stylesheet.
 */

import type { CSSProperties, ReactNode } from "react";

export type Tone = "cyan" | "amber" | "magenta" | "green" | "neutral";

export const toneColors: Record<Tone, { fg: string; bg: string; border: string }> = {
  cyan: { fg: "var(--cyan)", bg: "var(--cyan-soft)", border: "var(--cyan-border)" },
  amber: { fg: "var(--amber)", bg: "var(--amber-soft)", border: "var(--amber-border)" },
  magenta: { fg: "var(--magenta)", bg: "var(--magenta-soft)", border: "var(--magenta-border)" },
  green: { fg: "var(--green)", bg: "var(--green-soft)", border: "var(--green-border)" },
  neutral: { fg: "var(--ink-500)", bg: "var(--ink-50)", border: "var(--ink-100)" },
};

/** Score → tone. The same thresholds are used everywhere a score appears. */
export function scoreTone(score: number | null | undefined): Tone {
  if (score === null || score === undefined || Number.isNaN(score)) return "neutral";
  if (score >= 0.9) return "green";
  if (score >= 0.75) return "neutral";
  return "amber";
}

export function scoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return "var(--ink-300)";
  if (score >= 0.9) return "var(--green)";
  if (score >= 0.75) return "var(--ink-800)";
  return "var(--amber)";
}

export function Card({
  children,
  style,
  padded = true,
}: {
  children: ReactNode;
  style?: CSSProperties;
  padded?: boolean;
}) {
  return (
    <div
      style={{
        border: "1px solid var(--ink-100)",
        borderRadius: "var(--radius-lg)",
        background: "var(--ink-0)",
        padding: padded ? "var(--space-5)" : 0,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  size = "md",
  disabled,
  type = "button",
  full,
  style,
  ariaExpanded,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  type?: "button" | "submit";
  full?: boolean;
  style?: CSSProperties;
  ariaExpanded?: boolean;
}) {
  const palette: Record<string, CSSProperties> = {
    primary: {
      background: disabled ? "var(--ink-200)" : "var(--cyan-strong)",
      color: disabled ? "var(--ink-500)" : "var(--cyan-fg)",
      borderColor: disabled ? "var(--ink-200)" : "var(--cyan-strong)",
    },
    secondary: {
      background: "var(--ink-0)",
      color: "var(--ink-800)",
      borderColor: "var(--ink-200)",
    },
    ghost: { background: "transparent", color: "var(--ink-500)", borderColor: "transparent" },
    danger: {
      background: "var(--magenta-soft)",
      color: "var(--magenta)",
      borderColor: "var(--magenta-border)",
    },
  };
  const sizing: Record<string, CSSProperties> = {
    sm: { padding: "4px 10px", fontSize: "var(--text-xs)" },
    md: { padding: "8px 14px", fontSize: "var(--text-sm)" },
    lg: { padding: "12px 18px", fontSize: "var(--text-base)" },
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-expanded={ariaExpanded}
      style={{
        borderWidth: 1,
        borderStyle: "solid",
        borderRadius: "var(--radius-sm)",
        fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        width: full ? "100%" : undefined,
        transition: `background var(--dur-fast) var(--ease-out)`,
        ...palette[variant],
        ...sizing[size],
        ...style,
      }}
    >
      {children}
    </button>
  );
}

export function Chip({
  children,
  active,
  onClick,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
}) {
  const interactive = Boolean(onClick);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={interactive ? Boolean(active) : undefined}
      style={{
        border: `1px solid ${active ? "var(--cyan-strong)" : "var(--ink-200)"}`,
        background: active ? "var(--cyan-strong)" : "var(--ink-0)",
        color: active ? "var(--cyan-fg)" : "var(--ink-700)",
        padding: "4px 10px",
        borderRadius: "var(--radius-sm)",
        fontSize: "var(--text-xs)",
        cursor: interactive ? "pointer" : "default",
      }}
    >
      {children}
    </button>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  const colors = toneColors[tone];
  return (
    <span
      style={{
        background: colors.bg,
        color: colors.fg,
        padding: "2px 8px",
        borderRadius: "var(--radius-sm)",
        fontSize: "var(--text-xs)",
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

export function Meter({
  value,
  tone = "cyan",
  label,
}: {
  value: number;
  tone?: Tone;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      style={{
        height: 6,
        borderRadius: "var(--radius-full)",
        background: "var(--ink-100)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: toneColors[tone].fg,
          transition: `width var(--dur-slow) var(--ease-out)`,
        }}
      />
    </div>
  );
}

/**
 * A notice with an action. Used for every "this will not go well" moment:
 * low-resolution sources, photographs, and server-side failures.
 *
 * §3.2: being honest here is what prevents refund requests — so a notice
 * always says what will happen, what to do instead, and that nothing has
 * been charged.
 */
export function Notice({
  tone,
  title,
  children,
  actions,
}: {
  tone: Tone;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const colors = toneColors[tone];
  return (
    <div
      role="status"
      style={{
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        borderRadius: "var(--radius-lg)",
        padding: "var(--space-4)",
      }}
    >
      <div style={{ color: colors.fg, fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <p style={{ color: "var(--ink-700)", fontSize: "var(--text-sm)", margin: 0 }}>{children}</p>
      {actions && (
        <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-3)", flexWrap: "wrap" }}>
          {actions}
        </div>
      )}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <label
        htmlFor={htmlFor}
        style={{ fontSize: "var(--text-sm)", fontWeight: 500, color: "var(--ink-800)" }}
      >
        {label}
      </label>
      {children}
      {hint && (
        <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-400)", margin: 0 }}>{hint}</p>
      )}
    </div>
  );
}

export function Muted({ children, size = "sm" }: { children: ReactNode; size?: "xs" | "sm" }) {
  return (
    <span
      /* ink-400 on ink-25 is 3.48:1 — fine for a 20px label, not for the
         12px one this actually renders. */
      style={{
        color: "var(--ink-500)",
        fontSize: size === "xs" ? "var(--text-xs)" : "var(--text-sm)",
      }}
    >
      {children}
    </span>
  );
}

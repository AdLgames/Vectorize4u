/** Theme toggle. The attribute wins over the OS preference (see globals.css). */

export type Theme = "light" | "dark";

const KEY = "v4u.theme";

export function readTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(KEY);
  return value === "light" || value === "dark" ? value : null;
}

export function applyTheme(theme: Theme | null): void {
  const root = document.documentElement;
  if (theme) {
    root.setAttribute("data-theme", theme);
    window.localStorage.setItem(KEY, theme);
  } else {
    root.removeAttribute("data-theme");
    window.localStorage.removeItem(KEY);
  }
}

export function currentTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const explicit = readTheme();
  if (explicit) return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

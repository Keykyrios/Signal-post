import { useEffect, useState } from "react";

/** The CSS variables in index.css drive the page. Canvas and JS-computed colours in the
 *  vendored components cannot read CSS variables, so they get these resolved values. */
export const PALETTE = {
  light: { bg: "#f1f3f5", surface: "#fafbfc", ink: "#151a21", muted: "#536070", line: "#d5dbe2", accent: "#1b4f8f", action: "#1b4f8f", onAction: "#f6f9fc" },
  dark: { bg: "#12161b", surface: "#181d23", ink: "#e6eaef", muted: "#9ba7b4", line: "#2a323b", accent: "#86b4ee", action: "#2f63b0", onAction: "#f6f9fc" },
} as const;

export type Palette = (typeof PALETTE)["light"] | (typeof PALETTE)["dark"];

export function usePalette(): Palette & { dark: boolean } {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const q = window.matchMedia(query);
    const on = () => setDark(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return { ...(dark ? PALETTE.dark : PALETTE.light), dark };
}

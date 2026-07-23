"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import type { Theme } from "@/lib/types";

/**
 * Light/dark toggle.
 *
 * Renders a placeholder until mounted: the server cannot know which theme the
 * browser resolved, so rendering the real icon immediately guarantees a
 * hydration mismatch. Reserving the exact same box size means no layout shift
 * when the real button appears.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("masar-theme") as Theme | null;
    if (stored === "light" || stored === "dark") {
      setTheme(stored);
      return;
    }
    setTheme(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("masar-theme", next);
    } catch {
      // Private browsing: the toggle still works for this session.
    }
  }

  if (theme === null) {
    return <div className="h-9 w-9 rounded-lg" aria-hidden />;
  }

  return (
    <button
      onClick={toggle}
      className="grid h-9 w-9 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)] transition-all hover:border-[var(--accent-border)] hover:text-[var(--accent)] active:scale-95"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      title={theme === "dark" ? "Light mode" : "Dark mode"}
    >
      {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

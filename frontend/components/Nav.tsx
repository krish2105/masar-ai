"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "./ThemeToggle";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Chat" },
  { href: "/explore", label: "Explore" },
  { href: "/data", label: "Data" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--bg)]/85 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-2 px-3 sm:gap-4 sm:px-4">
        <Link href="/" className="flex items-baseline gap-2 shrink-0" aria-label="Masar AI home">
          <span
            className="text-[1.05rem] font-bold tracking-[0.06em]"
            style={{ fontFamily: "var(--font-arabic)" }}
          >
            مسار
          </span>
          <span className="text-[0.9rem] font-bold tracking-[0.14em] text-[var(--text)]">
            MASAR
            <span className="text-[var(--accent)]"> AI</span>
          </span>
        </Link>

        <nav className="flex items-center gap-1" aria-label="Main">
          {LINKS.map((link) => {
            const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-lg px-2.5 py-1.5 text-[0.82rem] font-medium transition-colors sm:px-3",
                  active
                    ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                    : "text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]",
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="ms-auto flex items-center gap-2">
          <span className="hidden sm:inline chip chip-idle" title="Source data provenance">
            archived open data
          </span>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

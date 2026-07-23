import type { Metadata, Viewport } from "next";
import { Inter, IBM_Plex_Sans_Arabic } from "next/font/google";
import "./globals.css";
import { ThemeScript } from "@/components/ThemeScript";
import { Nav } from "@/components/Nav";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const arabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-arabic",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Masar AI — Dubai Mobility Decision Intelligence",
  description:
    "Agentic RAG over Dubai RTA open data. Independent academic project — not affiliated with or endorsed by the Roads and Transport Authority.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f2ea" },
    { media: "(prefers-color-scheme: dark)", color: "#100f0d" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${arabic.variable}`}>
      <head>
        {/* Applies the stored theme before first paint so there is no flash. */}
        <ThemeScript />
      </head>
      <body className="min-h-screen flex flex-col">
        <Nav />
        <div className="flex-1 flex flex-col min-h-0">{children}</div>
        <footer className="border-t border-[var(--border)] px-4 py-3 text-[0.7rem] leading-relaxed text-[var(--text-faint)]">
          <div className="mx-auto max-w-[1600px]">
            <strong className="text-[var(--text-muted)]">Masar AI is an independent academic project.</strong>{" "}
            It is not affiliated with, endorsed by, or connected to the Roads and Transport Authority.
            It uses publicly available open data published by RTA via Dubai Pulse, recovered from
            public Internet Archive snapshots. Live operational data is not publicly available and is
            not simulated as live.
          </div>
        </footer>
      </body>
    </html>
  );
}

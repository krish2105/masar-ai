import { ImageResponse } from "next/og";

/**
 * The social card. Rendered by Satori, which ships only a Latin sans fallback —
 * so this is Latin-only on purpose. Putting the Arabic wordmark here without
 * bundling an Arabic font would render tofu boxes, which looks broken on every
 * shared link. The brand's Arabic identity lives in the app itself, where the
 * IBM Plex Arabic webfont is loaded.
 */
export const runtime = "edge";
export const alt = "Masar AI — Dubai Mobility Decision Intelligence";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#100f0d",
          color: "#ede9e3",
          padding: "72px 80px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <svg width="56" height="56" viewBox="0 0 100 100">
            <rect width="100" height="100" rx="24" fill="#2abfb2" />
            <path
              d="M28 68 C 28 46, 72 54, 72 32"
              stroke="#100f0d"
              strokeWidth="8"
              fill="none"
              strokeLinecap="round"
            />
            <circle cx="28" cy="68" r="9" fill="#100f0d" />
            <circle cx="72" cy="32" r="9" fill="#100f0d" />
          </svg>
          <div style={{ fontSize: 30, fontWeight: 700, letterSpacing: 3 }}>MASAR AI</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div style={{ fontSize: 64, fontWeight: 700, lineHeight: 1.08, maxWidth: 940 }}>
            Dubai mobility, answered with its sources.
          </div>
          <div style={{ fontSize: 28, color: "#2abfb2", fontWeight: 500 }}>
            Agentic RAG over RTA open data · 14-agent corrective loop · AED 0 inference
          </div>
        </div>

        <div style={{ fontSize: 20, color: "#8f887e" }}>
          Independent academic project — not affiliated with the Roads and Transport Authority
        </div>
      </div>
    ),
    { ...size },
  );
}

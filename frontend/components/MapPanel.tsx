"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { StationMarker } from "@/lib/types";
import { MODE_COLORS } from "@/lib/utils";

/**
 * MapLibre GL with free OpenStreetMap raster tiles — no Mapbox token, so no
 * credit card, which is a hard constraint of this build.
 *
 * The library is imported dynamically because it is large and WebGL-dependent;
 * loading it eagerly would block first paint on a tab most visitors never open.
 */
export function MapPanel({ stations }: { stations: StationMarker[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<import("maplibre-gl").Map | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!container.current || map.current) return;
    let cancelled = false;

    (async () => {
      try {
        const maplibre = await import("maplibre-gl");
        if (cancelled || !container.current) return;

        const dark =
          document.documentElement.getAttribute("data-theme") === "dark" ||
          (!document.documentElement.hasAttribute("data-theme") &&
            window.matchMedia("(prefers-color-scheme: dark)").matches);

        map.current = new maplibre.Map({
          container: container.current,
          style: {
            version: 8,
            sources: {
              osm: {
                type: "raster",
                tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                tileSize: 256,
                attribution: "© OpenStreetMap contributors",
              },
            },
            layers: [
              { id: "bg", type: "background", paint: { "background-color": dark ? "#100f0d" : "#f6f2ea" } },
              {
                id: "osm",
                type: "raster",
                source: "osm",
                paint: {
                  // Tinting the raster keeps OSM legible while matching the theme,
                  // without needing a paid vector style.
                  "raster-opacity": dark ? 0.55 : 0.85,
                  "raster-saturation": dark ? -0.6 : -0.25,
                  "raster-brightness-min": dark ? 0.05 : 0.15,
                },
              },
            ],
          },
          center: [55.28, 25.2],
          zoom: 9.6,
          attributionControl: { compact: true },
        });

        map.current.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance || stations.length === 0) return;

    let cancelled = false;
    (async () => {
      const maplibre = await import("maplibre-gl");
      if (cancelled || !map.current) return;

      document.querySelectorAll(".masar-marker").forEach((node) => node.remove());

      const bounds = new maplibre.LngLatBounds();
      for (const station of stations) {
        const element = document.createElement("div");
        element.className = "masar-marker";
        element.style.cssText = `width:9px;height:9px;border-radius:50%;cursor:pointer;
          background:${MODE_COLORS[station.mode] ?? "#2abfb2"};
          border:1.5px solid rgba(255,255,255,.85);
          box-shadow:0 0 0 1px rgba(0,0,0,.25);`;

        new maplibre.Marker({ element })
          .setLngLat([station.lon, station.lat])
          .setPopup(
            new maplibre.Popup({ offset: 12, closeButton: false }).setHTML(
              `<div style="font-family:system-ui;font-size:12px;line-height:1.45">
                 <strong>${escapeHtml(station.name_en)}</strong><br/>
                 ${station.name_ar ? `<span dir="rtl">${escapeHtml(station.name_ar)}</span><br/>` : ""}
                 <span style="opacity:.7">${escapeHtml(station.mode)}${
                   station.line ? ` · ${escapeHtml(station.line)}` : ""
                 }${station.zone != null ? ` · zone ${station.zone}` : ""}</span>
               </div>`,
            ),
          )
          .addTo(map.current);

        bounds.extend([station.lon, station.lat]);
      }

      if (!bounds.isEmpty()) {
        map.current.fitBounds(bounds, { padding: 48, maxZoom: 13, duration: 700 });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [stations]);

  if (failed) {
    return (
      <div className="grid h-full min-h-[18rem] place-items-center p-4 text-center text-[0.78rem] text-[var(--text-faint)]">
        The map could not load. Station coordinates are still available in the Evidence tab.
      </div>
    );
  }

  return (
    <div className="relative h-full min-h-[18rem]">
      <div ref={container} className="absolute inset-0" />
      {stations.length > 0 && (
        <div className="pointer-events-none absolute bottom-2 start-2 z-10 flex flex-wrap gap-1.5">
          {Object.entries(MODE_COLORS)
            .filter(([mode]) => stations.some((s) => s.mode === mode))
            .map(([mode, color]) => (
              <span
                key={mode}
                className="flex items-center gap-1 rounded-md bg-[var(--surface)]/90 px-1.5 py-0.5 text-[0.62rem] text-[var(--text-muted)] backdrop-blur"
              >
                <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                {mode}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c,
  );
}

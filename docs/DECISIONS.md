# Architecture Decision Log

Decisions that departed from `MASAR_AI_MASTER_BUILD_PROMPT.md`, or that the
document left open. §14 requires that genuine blockers be resolved with the most
conservative option that keeps the system running, and recorded here with the
reasoning.

---

## ADR-001 — Dubai Pulse is retired; source data from the Internet Archive

**Date:** 2026-07-24 · **Status:** accepted · **Supersedes:** §3.1, §3.2

### Context

§3.2 rests on one assumption: *"Bulk CSV download links are available
immediately without a key"*, making the CSV path primary and the API a later
refresh. Verification before writing any ingestion code found that assumption no
longer holds.

| Probe | Result |
|---|---|
| `www.dubaipulse.gov.ae/data/rta-bus/rta_bus_routes-open` | `301 → https://data.dubai` (homepage, not the dataset) |
| Every `dubaipulse.gov.ae/*` path tested | Redirects to `data.dubai/en/` |
| `api.dubaipulse.gov.ae/open/rta/...` | Alive, `401 Unauthorized application request` |
| `opendata.dubai.gov.ae`, `data.gov.ae`, `opendata.rta.ae` | No DNS / no connection |
| `data.dubai` catalogue | Liferay SPA, topic-organised, public dataset search returns nothing; Login / Portal Access gate |
| `bayanat.ae` | Live, but federal/Abu Dhabi ministries — not Dubai RTA operational data |

Both paths the spec depends on are therefore closed: the bulk CSV URLs no longer
resolve, and the surviving API gateway needs exactly the credentials §3.2 warned
can take 14 days.

### Decision

Recover the data from public Internet Archive snapshots of Dubai Pulse, and make
provenance a first-class column rather than a footnote.

Dubai Pulse served CKAN-style resource downloads at
`/dataset/{uuid}/resource/{uuid}/download/{stem}_{period}.csv`. The Archive holds
**1,274 unique such captures**, many current to January 2026. `WaybackClient`
queries the CDX index once, caches it, groups resources by filename, and fetches
the newest capture of each with the `id_` modifier so the original bytes are
returned rather than the Archive's HTML wrapper.

Verified by download before committing to the approach:

| Dataset | Evidence |
|---|---|
| `metro_passengers_trips_by_station_monthly` | `"2026","Jan","World Trade Centre Metro Station","25018"` |
| `metro_stations` | `location_id, zone_id, location_name_english, location_name_arabic, line_name, lon, lat, opening_date` |
| `bus_routes` | 736 rows: `route_name, route_type, direction, stop_name, stop_number` |
| `bus_passengers_trips_by_route_monthly` | monthly series 2020-12 → 2026-01 |

### Consequences

- **Positive.** The spec's hard requirement — *"fully demonstrable with zero API
  keys"* — is met more robustly than the original plan, which depended on a host
  that no longer serves the files. Coverage is *wider* than §3.3 scoped: tram,
  marine and network-length datasets were archived alongside the twelve.
- **Positive.** Provenance columns (`source_tier`, `source_url`, `captured_at`,
  `is_synthetic`) run from bronze through to the `[S1]` citation, so the UI is
  structurally incapable of showing archived data as live.
- **Negative.** The data is one step removed from RTA. `README.md` and
  `GOVERNANCE.md` state this plainly, and evidence cards show the capture date
  rather than a bare date.
- **Negative.** Recency is frozen at each dataset's last capture.
- **Retained.** `ApiSource` implements the `Source` protocol, so granted
  credentials become a configuration change, never a code change.

### Alternatives rejected

- **Synthetic data for everything.** Would have made the honesty disclaimer do
  work that real data does better, and destroyed the analytics story.
- **Wait for API credentials.** Up to 14 days, with no guarantee the legacy
  gateway survives the platform migration.
- **Scrape `data.dubai`.** Authentication-gated; scraping past a login on a
  government portal is not defensible.

---

## ADR-002 — Cap transaction-grain snapshot families, and publish the cap

**Date:** 2026-07-24 · **Status:** accepted

### Context

Two archived families are enormous, and profiling them before download revealed
the scale:

| Family | Files | Bytes/file | Total |
|---|---|---|---|
| `metro_ridership` | 24 | ~194 MB | **~4.4 GB** |
| `bus_ridership` | 31 | ~35 MB | **~1.0 GB** |
| `metro_passengers_trips_by_station_monthly` | 36 | ~2.7 KB | ~96 KB |
| `bus_passengers_trips_by_route_monthly` | 33 | ~5.1 KB | ~168 KB |

The two large families are transaction-grain. The analytical signal Masar's
golden set actually needs — station-level and route-level demand over time — is
in the monthly aggregates, four orders of magnitude smaller and *more* current
(to January 2026, versus 2025-05 and 2018 respectively).

The development machine had 38 GB free.

### Decision

Cap the two transaction-grain families (`metro_ridership` → 1 file,
`bus_ridership` → 2) and add a `max_bytes_per_file` guard (250 MB) enforced by a
HEAD request before any download.

Critically, **every cap is reported**. `Dataset.cap_rationale` states why in
prose; the bronze manifest records `coverage.capped` with available/retained/
dropped counts and `coverage.skipped_files` with a reason per file; the Phase 1
gate report prints `(capped 1/24)` beside the dataset. A cap that is not surfaced
reads as full coverage when it is not — which is the same class of error as
presenting archived data as live.

### Consequences

- Bronze lands in the low hundreds of MB rather than ~5.5 GB.
- One capture of each raw family is retained so the transaction grain remains
  inspectable and the schema is documented.
- `DATA_DICTIONARY.md` publishes the rationale per dataset.

---

## ADR-003 — Next.js 15 / React 19 / Tailwind v4 instead of Next.js 14

**Date:** 2026-07-24 · **Status:** accepted · **Amends:** §4.1

§4.1 specifies Next.js 14, written before 15 and Tailwind v4 were stable. The
App Router architecture is unchanged; Tailwind v4's CSS-first `@theme` makes the
light/dark token system materially cleaner, which matters because the build
carries two full themes. Node 20.20 supports it.

---

## ADR-004 — Desert Ink palette and a persistent agent rail

**Date:** 2026-07-24 · **Status:** accepted · **Amends:** §7

§7 fixes a near-black canvas, teal accent and amber corrective-loop highlight,
but defines no light mode, and the build requires a theme toggle.

**Palette — Desert Ink.** Warm neutrals (`#100F0D` dark, `#F6F2EA` light) with
the teal accent retained (`#2ABFB2` dark / `#0F766E` light, both ≥ 4.5:1) and
amber (`#E6A03C` / `#925807`) reserved *exclusively* for the corrective loop, so
that badge always means one thing. Warm off-white also reads better for Arabic
than pure white.

**Layout — persistent agent rail.** §7 places the agent timeline in a tabbed
panel alongside Evidence and Map. The system's central claim is that retrieval
strategy is a runtime decision; putting the only visible evidence of that behind
a tab makes the claim invisible to anyone who does not click it. The timeline is
instead pinned above the composer, permanently visible, costing ~90 px of
height. The full waterfall remains at `/trace/[id]`.

---

## ADR-005 — Fare rates in a cited config, never as constants

**Date:** 2026-07-24 · **Status:** accepted

§5.3 requires A11 to be deterministic Python. It does not say where the rates
come from, and a fare hardcoded in a function is one nobody can audit or update.

`config/fares.yaml` holds every rate with a `source`, an `effective_from`, and a
`verified_against_dataset` flag. A11 returns the citations for each rate it
applied; A13 renders them as declared assumptions.

This surfaced a real honesty problem worth stating: the archived `salik_tariff`
dataset carries **AED 4.00 flat, effective 2018-11**. RTA later introduced
variable peak pricing, which is in no dataset Masar holds. Rather than quietly
using a number found elsewhere, A11 uses the dataset-verified rate and every
Salik answer states its effective date and notes that a present-day peak-hour
cost would be higher. nol fare bands appear in no archived dataset at all, so
they are marked `verified_against_dataset: false` and every answer using them
says the figure is indicative.

---

## ADR-006 — CTE aliases excluded from the SQL table allowlist

**Date:** 2026-07-24 · **Status:** accepted

The first implementation of the A8 guard collected every `exp.Table` node and
checked it against the star-schema allowlist. A unit test for a legitimate
read-only CTE failed: `WITH monthly AS (...) SELECT * FROM monthly` was rejected
because `monthly` is not a star-schema table.

CTE names are query-local aliases, not tables. The guard now collects CTE
aliases while walking the tree — which it must do anyway to reject
data-modifying CTEs — and excludes them from the allowlist check. All four
safety layers are unaffected; only the false positive is removed.

Worth recording because it is the exact failure mode a guard without
false-negative tests would ship with: a guard that rejects everything passes
every injection test.

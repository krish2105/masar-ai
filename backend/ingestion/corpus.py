"""Corpus generation for the vector index.

§3.4 asks for a curated document corpus so questions like "which zone is Union
in?" or "what does the ridership dataset contain?" have prose to retrieve, not
just rows to aggregate.

WHY THESE DOCUMENTS ARE GENERATED RATHER THAN TRANSCRIBED
---------------------------------------------------------
The obvious corpus is RTA's public service pages. Writing those from memory
would mean inventing government service descriptions — documented fees, required
paperwork, opening hours — that neither I nor the reader can verify. In a system
whose entire claim is that every sentence is traceable to a source, fabricated
service content would be the single worst thing in the repository, and no
disclaimer would repair it.

So every document here is generated from something the system actually holds:
a loaded database row, a bronze manifest, a data quality report, or the cited
fare configuration. Each carries `source_url` and `grounded_in` front-matter
naming exactly what produced it. The corpus is smaller than a scraped one and
considerably more defensible.

Documents are emitted bilingually wherever the underlying data carries Arabic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from backend.services.logging import get_logger

log = get_logger(__name__)

TODAY = datetime.now(tz=UTC).strftime("%Y-%m-%d")


def _front_matter(
    *,
    doc_id: str,
    title: str,
    lang: str,
    category: str,
    source_url: str,
    grounded_in: list[str],
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "doc_id": doc_id,
        "title": title,
        "lang": lang,
        "service_category": category,
        "source_url": source_url,
        "retrieved_date": TODAY,
        "grounded_in": grounded_in,
        "generated": True,
        "disclaimer": (
            "Generated from data Masar AI holds. Independent academic project; "
            "not affiliated with or endorsed by RTA."
        ),
    }
    if extra:
        payload.update(extra)
    return "---\n" + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False) + "---\n\n"


class CorpusBuilder:
    def __init__(self, gold_dir: Path, bronze_dir: Path, dq_dir: Path, corpus_dir: Path) -> None:
        self.gold_dir = gold_dir
        self.bronze_dir = bronze_dir
        self.dq_dir = dq_dir
        self.corpus_dir = corpus_dir
        (self.corpus_dir / "en").mkdir(parents=True, exist_ok=True)
        (self.corpus_dir / "ar").mkdir(parents=True, exist_ok=True)
        self.written: list[Path] = []

    # ------------------------------------------------------------- helpers --
    def _gold(self, name: str) -> pl.DataFrame:
        path = self.gold_dir / f"{name}.parquet"
        return pl.read_parquet(path) if path.exists() else pl.DataFrame()

    def _write(self, lang: str, slug: str, body: str) -> None:
        path = self.corpus_dir / lang / f"{slug}.md"
        path.write_text(body, encoding="utf-8")
        self.written.append(path)

    # ------------------------------------------------- 1. dataset dictionaries
    def build_dataset_dictionaries(self) -> int:
        """One document per dataset, from its bronze manifest and DQ report."""
        count = 0
        manifest_path = self.bronze_dir / "_manifest.json"
        if not manifest_path.exists():
            log.warning("corpus.no_bronze_manifest")
            return 0

        run = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in run.get("datasets", []):
            dataset_id = entry["dataset_id"]
            dq_files = sorted(self.dq_dir.glob(f"{dataset_id}_*.json"))
            dq = json.loads(dq_files[-1].read_text(encoding="utf-8")) if dq_files else {}

            periods = entry.get("data_period_range")
            coverage = entry.get("coverage") or {}
            capped = coverage.get("capped")

            lines = [
                _front_matter(
                    doc_id=f"dataset-{dataset_id}",
                    title=f"Dataset: {dataset_id}",
                    lang="en",
                    category="data_dictionary",
                    source_url=entry.get("landing_page", ""),
                    grounded_in=[f"bronze manifest for {dataset_id}", "data quality report"],
                    extra={"dataset_id": dataset_id, "domain": entry.get("domain")},
                ),
                f"# {dataset_id}\n",
                f"**Role in Masar AI.** {entry.get('role', '')}\n",
                "## Provenance\n",
                f"- Original Dubai Pulse dataset: `{entry.get('dubai_pulse_slug', '')}`",
                f"- Original landing page: {entry.get('landing_page', '')}",
                "- Recovered from: public Internet Archive snapshots of Dubai Pulse",
                f"- Files recovered: {entry.get('file_count', 0)}",
                f"- Total size: {entry.get('total_bytes', 0):,} bytes",
            ]
            if entry.get("capture_dates"):
                captures = entry["capture_dates"]
                lines.append(f"- Archive capture dates: {captures[0]} to {captures[-1]}")
            if periods:
                lines.append(f"- Data period covered: **{periods[0]} to {periods[1]}**")
            else:
                lines.append("- Data period: static reference table (no time dimension)")

            if capped:
                lines += [
                    "",
                    "## Coverage limitation\n",
                    f"Only {capped['retained']} of {capped['available']} archived captures "
                    f"were retained ({capped['dropped']} skipped).\n",
                    f"> {capped['rationale']}\n",
                    "Analysis over this dataset is therefore a **sample**, not the full "
                    "published history.",
                ]

            if dq:
                counts = dq.get("row_counts", {})
                lines += [
                    "",
                    "## Data quality\n",
                    f"- Rows read: {counts.get('in', 0):,}",
                    f"- Rows after typing, deduplication and validation: {counts.get('out', 0):,}",
                    f"- Duplicate rows removed: {counts.get('deduplicated', 0):,}",
                    f"- Rows quarantined: {counts.get('quarantined', 0):,}",
                    f"- Coercion failures: {sum(dq.get('coercion_failures', {}).values()):,}",
                    f"- Quality gate: {'passed' if dq.get('passed') else 'FAILED'}",
                ]
                if dq.get("natural_key"):
                    lines.append(f"- Deduplicated on: `{', '.join(dq['natural_key'])}`")
                if dq.get("warnings"):
                    lines += ["", "### Warnings\n"]
                    lines += [f"- {w}" for w in dq["warnings"][:8]]

                columns = dq.get("columns", [])
                if columns:
                    lines += [
                        "",
                        "## Columns\n",
                        "| column | type | null rate | distinct | example |",
                        "|---|---|---|---|---|",
                    ]
                    for column in columns:
                        if column["name"].startswith("_"):
                            continue
                        example = (column.get("sample_values") or [""])[0]
                        example = str(example).replace("|", "\\|")[:40]
                        lines.append(
                            f"| `{column['name']}` | {column['dtype']} | "
                            f"{column['null_rate']:.1%} | {column['distinct_count']:,} | {example} |"
                        )

            self._write("en", f"dataset-{dataset_id}", "\n".join(lines) + "\n")
            count += 1

        log.info("corpus.dataset_dictionaries", documents=count)
        return count

    # --------------------------------------------------- 2. line/station guides
    def build_line_guides(self) -> int:
        """One document per rail line, listing its stations, zones and geometry."""
        stations = self._gold("dim_station")
        if stations.is_empty():
            return 0

        count = 0
        rail = stations.filter(
            pl.col("mode").is_in(["Metro", "Tram"]) & pl.col("line_name").is_not_null()
        )
        for (line_name,), group in rail.group_by(["line_name"], maintain_order=True):
            if not line_name:
                continue
            group = group.sort("station_name_en")
            slug = str(line_name).lower().replace(" ", "-").replace("/", "-")
            zones = sorted({z for z in group.get_column("zone_id").to_list() if z is not None})
            mode = group.get_column("mode")[0]

            en = [
                _front_matter(
                    doc_id=f"line-{slug}",
                    title=f"{line_name} — stations and fare zones",
                    lang="en",
                    category="network_reference",
                    source_url="https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_stations_gis-open",
                    grounded_in=["dim_station (gold layer)"],
                    extra={"line_name": line_name, "mode": mode},
                ),
                f"# {line_name}\n",
                f"The {line_name} is part of Dubai's {mode.lower()} network. Masar AI holds "
                f"**{group.height} stations** on this line, spanning fare "
                f"{'zones ' + ', '.join(str(z) for z in zones) if zones else 'zones (not recorded)'}.\n",
                "## Stations\n",
                "| station | Arabic | fare zone | latitude | longitude |",
                "|---|---|---|---|---|",
            ]
            ar_rows = []
            for row in group.iter_rows(named=True):
                name_en = row["station_name_en"] or ""
                name_ar = row["station_name_ar"] or ""
                zone = row["zone_id"] if row["zone_id"] is not None else "—"
                lat = f"{row['latitude']:.6f}" if row["latitude"] is not None else "—"
                lon = f"{row['longitude']:.6f}" if row["longitude"] is not None else "—"
                en.append(f"| {name_en} | {name_ar} | {zone} | {lat} | {lon} |")
                if name_ar:
                    ar_rows.append(f"| {name_ar} | {name_en} | {zone} |")

            en += [
                "",
                "## Fare note\n",
                "Fares are charged by the number of fare zones a journey crosses, not by "
                "distance. A journey within one zone is charged the one-zone fare; a journey "
                "between adjacent zones is charged the two-zone fare.\n",
                "## Data note\n",
                "Station data is recovered from archived RTA open data and reflects the "
                "network as published at the capture date. Newer stations or renamed "
                "stations may not be present.",
            ]
            self._write("en", f"line-{slug}", "\n".join(en) + "\n")
            count += 1

            if ar_rows:
                ar = [
                    _front_matter(
                        doc_id=f"line-{slug}-ar",
                        title=f"{line_name} — المحطات ومناطق الأجرة",
                        lang="ar",
                        category="network_reference",
                        source_url="https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_stations_gis-open",
                        grounded_in=["dim_station (gold layer)"],
                        extra={"line_name": line_name, "mode": mode},
                    ),
                    f"# {line_name}\n",
                    f"يحتوي هذا الخط على **{len(ar_rows)} محطة** في شبكة دبي.\n",
                    "## المحطات\n",
                    "| المحطة | بالإنجليزية | منطقة الأجرة |",
                    "|---|---|---|",
                    *ar_rows,
                    "",
                    "## ملاحظة حول الأجرة\n",
                    "تُحتسب الأجرة حسب عدد مناطق الأجرة التي تعبرها الرحلة، وليس حسب المسافة.\n",
                    "## ملاحظة حول البيانات\n",
                    "بيانات المحطات مستردة من البيانات المفتوحة المؤرشفة للهيئة، "
                    "وتعكس الشبكة كما نُشرت في تاريخ الأرشفة.",
                ]
                self._write("ar", f"line-{slug}-ar", "\n".join(ar) + "\n")
                count += 1

        log.info("corpus.line_guides", documents=count)
        return count

    # ------------------------------------------------------- 3. zone reference
    def build_zone_guides(self) -> int:
        """One document per fare zone — the join between geography and fares."""
        stations = self._gold("dim_station")
        if stations.is_empty() or "zone_id" not in stations.columns:
            return 0

        count = 0
        zoned = stations.filter(pl.col("zone_id").is_not_null())
        for (zone,), group in zoned.group_by(["zone_id"], maintain_order=True):
            modes = sorted(set(group.get_column("mode").to_list()))
            names = [n for n in group.get_column("station_name_en").to_list() if n]
            body = [
                _front_matter(
                    doc_id=f"zone-{zone}",
                    title=f"Fare zone {zone}",
                    lang="en",
                    category="fare_reference",
                    source_url="https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_stations_gis-open",
                    grounded_in=["dim_station (gold layer)", "config/fares.yaml"],
                    extra={"zone_id": int(zone)},
                ),
                f"# Fare zone {zone}\n",
                f"Masar AI holds **{group.height} stations** in fare zone {zone}, "
                f"across {', '.join(modes)}.\n",
                "## Stations in this zone\n",
                *[f"- {name}" for name in sorted(names)],
                "",
                "## How zones determine fare\n",
                "nol fares depend on how many zones a journey crosses:\n",
                "- Travel within a single zone: 1-zone fare",
                "- Travel between two zones: 2-zone fare",
                "- Travel across three or more zones: 3-zone fare (RTA does not price beyond three)\n",
                "Gold class carriages are charged at double the standard fare.\n",
                "Exact fare amounts are computed by Masar's deterministic calculator, which "
                "reports the source and effective date of every rate it applies. nol fare "
                "bands are not present in any archived RTA dataset Masar holds, so they are "
                "treated as indicative — confirm current fares at rta.ae.",
            ]
            self._write("en", f"zone-{zone}", "\n".join(body) + "\n")
            count += 1

        log.info("corpus.zone_guides", documents=count)
        return count

    # ------------------------------------------------------- 4. mode overviews
    def build_mode_overviews(self) -> int:
        """One document per transport mode, from the routes, stations and facts."""
        stations = self._gold("dim_station")
        routes = self._gold("dim_route")
        facts = self._gold("fact_ridership_monthly")
        if routes.is_empty():
            return 0

        count = 0
        for mode in sorted(set(routes.get_column("mode").to_list())):
            if not mode:
                continue
            mode_routes = routes.filter(pl.col("mode") == mode)
            mode_stations = (
                stations.filter(pl.col("mode") == mode) if not stations.is_empty() else pl.DataFrame()
            )
            mode_facts = (
                facts.filter((pl.col("mode") == mode) & ~pl.col("scale_anomaly"))
                if not facts.is_empty() and "scale_anomaly" in facts.columns
                else pl.DataFrame()
            )

            body = [
                _front_matter(
                    doc_id=f"mode-{mode.lower()}",
                    title=f"{mode} network overview",
                    lang="en",
                    category="network_reference",
                    source_url="https://www.dubaipulse.gov.ae/",
                    grounded_in=["dim_route", "dim_station", "fact_ridership_monthly"],
                    extra={"mode": mode},
                ),
                f"# {mode} network\n",
                f"- Routes held: **{mode_routes.height}**",
                f"- Stations held: **{mode_stations.height if not mode_stations.is_empty() else 0}**",
            ]

            lengths = mode_routes.get_column("route_length_km").drop_nulls()
            if lengths.len():
                body.append(f"- Mean route length: {lengths.mean():.1f} km")
            stops = mode_routes.get_column("stop_count").drop_nulls()
            if stops.len():
                body.append(f"- Mean stops per route: {stops.mean():.0f}")

            if not mode_facts.is_empty():
                periods = sorted(set(mode_facts.get_column("date_key").to_list()))
                body += [
                    "",
                    "## Ridership data held\n",
                    f"- Comparable periods: {len(periods)} "
                    f"({periods[0][:4]}-{periods[0][4:]} to {periods[-1][:4]}-{periods[-1][4:]})",
                    f"- Grain: per {mode_facts.get_column('grain')[0]}",
                ]
                top = (
                    mode_facts.group_by("entity_name")
                    .agg(pl.col("trips").sum().alias("total"))
                    .sort("total", descending=True)
                    .head(10)
                )
                body += ["", "### Busiest by total recorded trips\n"]
                body += [
                    f"{i}. {row['entity_name']} — {row['total']:,.0f} trips"
                    for i, row in enumerate(top.iter_rows(named=True), 1)
                ]

            longest = mode_routes.sort("stop_count", descending=True).head(5)
            if longest.height:
                body += ["", "## Routes with the most stops\n"]
                body += [
                    f"- **{row['route_number']}**"
                    + (f" — {row['origin_en']} to {row['destination_en']}" if row["origin_en"] else "")
                    + (f" ({row['stop_count']} stops)" if row["stop_count"] else "")
                    for row in longest.iter_rows(named=True)
                ]

            body += [
                "",
                "## Limitations\n",
                "- No real-time vehicle position or disruption data is published by RTA as "
                "open data, so Masar reasons from published schedules and network topology only.",
                "- Figures come from archived snapshots and reflect the capture date shown on "
                "each citation, not today.",
            ]
            self._write("en", f"mode-{mode.lower()}", "\n".join(body) + "\n")
            count += 1

        log.info("corpus.mode_overviews", documents=count)
        return count

    # ------------------------------------------------------- 5. fare reference
    def build_fare_reference(self) -> int:
        from backend.agents.a11_calculator import load_fares

        fares = load_fares()
        nol, salik = fares["nol"], fares["salik"]

        en = [
            _front_matter(
                doc_id="fares-nol",
                title="nol card fares and how they are calculated",
                lang="en",
                category="fare_reference",
                source_url=nol["source"],
                grounded_in=["config/fares.yaml"],
            ),
            "# nol fares\n",
            "Public transport in Dubai is paid for with a nol card. The fare depends on "
            "the **number of fare zones** a journey crosses, and on the card type.\n",
            "## Card types\n",
            "| card | fare multiplier | card cost (AED) |",
            "|---|---|---|",
        ]
        for key, card in nol["card_types"].items():
            en.append(f"| {card['label_en']} ({key}) | ×{card['multiplier']} | {card['card_cost']:.2f} |")

        en += [
            "",
            "## Fare by zones crossed\n",
            "| zones | standard fare (AED) |",
            "|---|---|",
            *[f"| {z} | {f:.2f} |" for z, f in nol["zone_fares"].items()],
            "",
            f"Journeys crossing more than {nol['max_zones']} zones are charged at the "
            f"{nol['max_zones']}-zone rate.\n",
            "## Passes\n",
            *[f"- {k.replace('_', ' ').title()}: AED {v:.2f}" for k, v in nol["passes"].items()],
            "",
            "## How Masar calculates fares\n",
            "All fare arithmetic is performed by deterministic Python, never generated by a "
            "language model. Every calculation returns its inputs as declared assumptions and "
            "cites the source and effective date of each rate applied.\n",
            "## Accuracy caveat\n",
            f"These bands are transcribed from published RTA tariffs effective "
            f"{nol['effective_from']}. They are **not** present in any archived RTA dataset "
            "Masar holds, so they cannot be cross-checked programmatically and are treated as "
            "indicative. Confirm current fares at rta.ae before relying on them.",
        ]
        self._write("en", "fares-nol", "\n".join(en) + "\n")

        salik_doc = [
            _front_matter(
                doc_id="fares-salik",
                title="Salik road toll",
                lang="en",
                category="fare_reference",
                source_url=salik["source"],
                grounded_in=["dim_salik_tariff (gold layer)", "config/fares.yaml"],
            ),
            "# Salik toll\n",
            "Salik is Dubai's automated road toll. A charge applies each time a vehicle "
            "passes a toll gate.\n",
            f"## Rate held by Masar\n",
            f"**AED {salik['flat_rate_per_crossing']:.2f} per gate crossing**, effective "
            f"{salik['effective_from']}.\n",
            "This rate is verified against the archived RTA tariff dataset.\n",
            "## Important limitation\n",
            "RTA subsequently introduced **variable peak pricing**, under which the charge "
            "differs by time of day. That change is not present in any dataset Masar holds. "
            "A present-day peak-hour crossing therefore costs more than the figure above, and "
            "every Salik calculation Masar produces states this explicitly.\n",
            "## Drive versus transit\n",
            "When comparing driving with public transport, Masar includes fuel, Salik and "
            "parking, and declares each assumption. It excludes vehicle depreciation, "
            "insurance, registration and maintenance, so the true cost of driving is higher "
            "than the comparison shows.",
        ]
        self._write("en", "fares-salik", "\n".join(salik_doc) + "\n")

        ar = [
            _front_matter(
                doc_id="fares-nol-ar",
                title="أجرة بطاقة نول",
                lang="ar",
                category="fare_reference",
                source_url=nol["source"],
                grounded_in=["config/fares.yaml"],
            ),
            "# أجرة بطاقة نول\n",
            "تُدفع أجرة النقل العام في دبي باستخدام بطاقة نول. تعتمد الأجرة على "
            "**عدد مناطق الأجرة** التي تعبرها الرحلة، وعلى نوع البطاقة.\n",
            "## الأجرة حسب عدد المناطق\n",
            "| عدد المناطق | الأجرة (درهم) |",
            "|---|---|",
            *[f"| {z} | {f:.2f} |" for z, f in nol["zone_fares"].items()],
            "",
            "## أنواع البطاقات\n",
            *[f"- {c['label_ar']}: ×{c['multiplier']}" for c in nol["card_types"].values()],
            "",
            "## ملاحظة حول الدقة\n",
            "هذه الأسعار غير موجودة في أي مجموعة بيانات مؤرشفة لدى النظام، لذا تُعامل "
            "كأسعار استرشادية. يُرجى التأكد من الأسعار الحالية عبر موقع الهيئة.",
        ]
        self._write("ar", "fares-nol-ar", "\n".join(ar) + "\n")

        log.info("corpus.fare_reference", documents=3)
        return 3

    # ------------------------------------------------- 6. capability & limits
    def build_capability_docs(self) -> int:
        """What the system can and cannot answer. A1 and A13 both retrieve these."""
        docs = {
            "limits-realtime": (
                "Real-time transport data availability",
                "capability",
                "# Real-time data is not available\n\n"
                "RTA does **not** publish real-time vehicle positions, live arrival "
                "predictions, or service disruption feeds as open data. Masar AI therefore "
                "cannot answer:\n\n"
                "- Where is bus route 13 right now?\n"
                "- When is the next metro at Union?\n"
                "- Is there a delay on the Red Line today?\n\n"
                "What Masar can do instead is reason from **network topology and published "
                "schedules**: which routes serve a stop, how many interchanges a journey "
                "needs, how far apart two stops are, and how ridership has behaved "
                "historically.\n\n"
                "Masar never simulates live data. When asked a real-time question it says "
                "the data is not publicly available and offers the schedule-based "
                "alternative.\n"
            ),
            "limits-data-currency": (
                "How current is the data?",
                "capability",
                "# Data currency\n\n"
                "Masar AI's source data comes from public Internet Archive snapshots of "
                "the Dubai Pulse open data platform, which was retired and now redirects to "
                "a portal whose catalogue requires authentication.\n\n"
                "Consequences a user should know:\n\n"
                "1. **Every figure has a capture date**, shown on its citation. A figure is "
                "accurate as of that date, not today.\n"
                "2. **Recency varies sharply by dataset.** Metro station ridership runs to "
                "January 2026; the Salik tariff table stops in 2022.\n"
                "3. **Some series are not internally comparable.** Where a dataset's later "
                "captures use a different unit or reporting period from its earlier ones, "
                "those periods are flagged and excluded from trend calculations, and the "
                "limitation is stated in the answer rather than hidden.\n\n"
                "Masar is an independent academic project and is not affiliated with, "
                "endorsed by, or connected to RTA.\n"
            ),
            "limits-journey-planning": (
                "How journey reasoning works",
                "capability",
                "# Journey reasoning\n\n"
                "Masar is **not a journey planner** and does not attempt to be one. It has "
                "no timetable data, no live positions, and no routing engine.\n\n"
                "What it does have is the route-to-stop network. From that it can determine "
                "which routes serve a given stop, whether two stops share a route, roughly "
                "how far apart points are (great-circle distance), and how many interchanges "
                "a journey would need.\n\n"
                "It reports **distance and interchange count**. It never invents a journey "
                "duration, because it has no data from which one could be derived. For an "
                "actual journey plan with times, use RTA's own S'hail app or rta.ae.\n"
            ),
            "about-masar": (
                "What Masar AI is",
                "capability",
                "# About Masar AI\n\n"
                "Masar (مسار, 'route' or 'path') is a decision-intelligence layer over "
                "Dubai's published open transport data. It answers multi-step questions that "
                "require combining several kinds of evidence — service documentation, "
                "ridership facts, geography, and cost arithmetic — in a single answer.\n\n"
                "## How it answers\n\n"
                "A planning agent decides, per question, which sources to consult. It can "
                "run hybrid document retrieval, query the analytical database, compute "
                "distances, and run deterministic fare arithmetic — in parallel where the "
                "sub-tasks are independent.\n\n"
                "A grading agent then scores the assembled evidence on coverage, "
                "specificity, recency and source authority. If the evidence is insufficient "
                "it names the gaps and sends the question back to be re-planned, up to three "
                "times, before answering with an explicit low-confidence caveat.\n\n"
                "## Guarantees\n\n"
                "- Every factual claim carries a citation resolving to a specific dataset "
                "row or document.\n"
                "- All arithmetic is deterministic Python. Language models never compute "
                "numbers in this system.\n"
                "- Answers are given in the language of the question.\n"
                "- Where the data cannot support an answer, Masar says so rather than "
                "guessing.\n"
            ),
        }

        for slug, (title, category, body) in docs.items():
            content = (
                _front_matter(
                    doc_id=slug,
                    title=title,
                    lang="en",
                    category=category,
                    source_url="https://github.com/krish2105",
                    grounded_in=["system design", "docs/DECISIONS.md"],
                )
                + body
            )
            self._write("en", slug, content)

        ar_body = (
            _front_matter(
                doc_id="about-masar-ar",
                title="عن مسار",
                lang="ar",
                category="capability",
                source_url="https://github.com/krish2105",
                grounded_in=["system design"],
            )
            + "# عن مسار\n\n"
            "مسار هو نظام ذكاء قراري يعتمد على البيانات المفتوحة المنشورة لهيئة الطرق "
            "والمواصلات في دبي.\n\n"
            "## ضمانات النظام\n\n"
            "- كل معلومة مذكورة في الإجابة مرفقة بمصدرها.\n"
            "- جميع الحسابات تُنفَّذ ببرمجة حتمية، ولا تُولَّد بواسطة نموذج لغوي.\n"
            "- تكون الإجابة بلغة السؤال دائماً.\n"
            "- إذا لم تكن البيانات كافية، يوضح النظام ذلك بدلاً من التخمين.\n\n"
            "## ملاحظة مهمة\n\n"
            "لا تنشر الهيئة بيانات مباشرة عن مواقع المركبات أو الأعطال، لذلك يعتمد النظام "
            "على الجداول المنشورة وبنية الشبكة فقط.\n\n"
            "مسار مشروع أكاديمي مستقل وغير تابع لهيئة الطرق والمواصلات.\n"
        )
        self._write("ar", "about-masar-ar", ar_body)

        log.info("corpus.capability_docs", documents=len(docs) + 1)
        return len(docs) + 1

    # ------------------------------------------------------------------- run --
    def build_all(self) -> dict[str, int]:
        counts = {
            "dataset_dictionaries": self.build_dataset_dictionaries(),
            "line_guides": self.build_line_guides(),
            "zone_guides": self.build_zone_guides(),
            "mode_overviews": self.build_mode_overviews(),
            "fare_reference": self.build_fare_reference(),
            "capability_docs": self.build_capability_docs(),
        }
        counts["total"] = sum(counts.values())
        return counts

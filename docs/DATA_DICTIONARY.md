# Data Dictionary

Every dataset Masar holds, where it came from, and what survived transformation.
Generated from `data/bronze/_manifest.json` and `reports/dq/`. The same
information is served live at `/api/v1/datasets` and rendered at `/data`.

**All source data is recovered from public Internet Archive snapshots of the
retired Dubai Pulse platform.** Original dataset slugs are retained for citation
lineage. See [GOVERNANCE.md](GOVERNANCE.md).

---

## Bronze — 19 datasets recovered, 171 files, 275 MB

| dataset | domain | files | rows in | rows out | data period | capped |
|---|---|---:|---:|---:|---|---|
| `bus_ridership` | bus | 2 | 1,595,534 | 1,583,627 | 2025-04-04 → 2025-04-05 | 2/31 |
| `bus_routes` | bus | 1 | 735 | 487 | static | — |
| `bus_stops` | bus | 1 | 182,466 | 4,319 | static | — |
| `bus_trips_monthly` | bus | 33 | 6,630 | 6,004 | 2020-12-20 → 2025-09-20 | — |
| `marine_stations` | marine | 1 | 59 | 59 | static | — |
| `marine_trips_by_station_monthly` | marine | 16 | 1,057 | 1,057 | 2021-02-20 → 2025-02-20 | — |
| `metro_lines` | rail | 1 | 2 | 2 | static | — |
| `metro_ridership` | rail | 1 | 657,808 | 580,129 | 2025-03-08 → 2025-03-08 | 1/24 |
| `metro_stations` | rail | 1 | 56 | 55 | static | — |
| `metro_trips_by_station_monthly` | rail | 36 | 2,067 | 1,007 | 2021-05-20 → 2026-01-20 | — |
| `modal_split_monthly` | multimodal | 20 | 22,894 | 982 | 2021-05-20 → 2024-05-20 | — |
| `routes_stops` | multimodal | 1 | 18,382 | 18,382 | static | — |
| `salik_tariff` | roads | 14 | 36 | 34 | 2018-12-20 → 2022-01-20 | — |
| `taxi_drivers` | taxi | 18 | 178 | 135 | 2021-02-20 → 2024-02-20 | — |
| `taxi_stands` | taxi | 1 | 147 | 147 | static | — |
| `tram_lines` | rail | 1 | 1 | 1 | static | — |
| `tram_stations` | rail | 1 | 11 | 11 | static | — |
| `tram_trips_by_station_monthly` | rail | 21 | 253 | 176 | 2021-04-20 → 2025-04-22 | — |
| `transport_stations` | multimodal | 1 | 137 | 137 | static | — |
### Coverage caps

Two transaction-grain families are sampled rather than fully ingested. Both
caps are recorded in the bronze manifest and badged in the UI.

| Dataset | Retained | Rationale |
|---|---|---|
| `metro_ridership` | 1 of 24 | ~194 MB per capture (~4.4 GB total). `metro_trips_by_station_monthly` carries the same station-level demand signal at 2.7 KB per period and runs to January 2026. One capture is kept so the raw grain stays inspectable. |
| `bus_ridership` | 2 of 31 | ~35 MB per capture (~1.0 GB total) of 2018 transaction records. `bus_trips_monthly` covers the same ground at 5 KB per period. |

### Not recoverable

`rta_salik_tolling_gates_location-open` — the Internet Archive holds the
dataset's landing page but no CSV capture of its resources. `dim_salik_gate` is
created empty so queries return no rows rather than "relation does not exist".

---

## Gold — the star schema

This is the only surface the Text-to-SQL agent may query. Full column
documentation lives in `backend/config/schema_card.md`, which is what the agent
actually reads.

| table | rows | key columns |
|---|---:|---|
| `bridge_route_stop` | 18,346 | `route_number`, `mode`, `stop_id`, `stop_name_en`, `stop_order`, `direction`, `latitude`, `longitude`, `route_key` |
| `dim_date` | 63 | `date_key`, `full_date`, `year`, `month`, `month_name_en`, `month_name_ar`, `quarter`, `year_month` |
| `dim_route` | 236 | `route_number`, `route_name_en`, `route_name_ar`, `mode`, `route_type`, `origin_en`, `destination_en`, `operator`, `route_length_km` |
| `dim_salik_gate` | 0 | `gate_id`, `gate_name_en`, `gate_name_ar`, `latitude`, `longitude` |
| `dim_salik_tariff` | 34 | `year`, `month_raw`, `fare_aed`, `month_num`, `date_key` |
| `dim_station` | 152 | `station_id`, `station_name_en`, `station_name_ar`, `mode`, `line_name`, `zone_id`, `latitude`, `longitude`, `opened_on` |
| `dim_stop` | 4,319 | `stop_id`, `stop_name_en`, `stop_name_ar`, `mode`, `street_name`, `latitude`, `longitude`, `stop_type` |
| `dim_taxi_driver_profile` | 135 | `report_date`, `operator_type`, `operator_name`, `driver_count` |
| `dim_taxi_stand` | 147 | `stand_id`, `stand_name_en`, `latitude`, `longitude` |
| `fact_modal_split_monthly` | 51 | `date_key`, `year`, `month_num`, `month_raw`, `transport_type`, `trips` |
| `fact_ridership_monthly` | 7,187 | `year`, `month_raw`, `mode`, `grain`, `entity_name`, `trips`, `month_num`, `date_key`, `period_scale_ratio` |
Every table additionally carries `source_dataset`, `source_url`, `captured_at`,
`source_tier` and `is_synthetic`, so any row resolves back to the archived file
it came from.

### Columns that need explaining

**`fact_ridership_monthly.grain`** — `route` for Bus, `station` for
Metro/Tram/Marine. The grain genuinely differs by mode, so it is an explicit
column rather than something to infer.

**`fact_ridership_monthly.scale_anomaly`** — `TRUE` when a period's magnitude is
inconsistent with the rest of its mode. Metro captures from 2025–26 report
values ~20× smaller than 2021–22 for the same 53 stations; the later files use a
different unit or reporting period that the published schema does not state.
**Any cross-period aggregate must filter these out.** Ranking *within* a single
period is still valid, because relative order holds even when the unit is
unknown.

**`dim_station.station_key`** — `station_id` is unique only within a mode, so
the surrogate is `{mode}_{station_id}`. Two source datasets identify the same
physical station by different schemes; deduplicating on a normalised name
within mode took the metro count from 110 to 63, which matches the real network.

**`dim_station.station_name_ar_norm`** — Arabic folded for search (alef unified,
tatweel and diacritics stripped). Match Arabic against this column; display
`station_name_ar`.

### Compatibility aliases

`questions.yaml` was authored before the data was recovered, against a
hypothesised schema. These generated columns let its reference queries run
unchanged where the data supports them:

| Alias | Resolves to | Note |
|---|---|---|
| `dim_route.route_id`, `bridge_route_stop.route_id` | `route_key` | |
| `dim_route.is_active` | always `TRUE` | The archive holds no deactivation flag |
| `dim_station.line_name_en`, `line_name_ar` | `line_name` | **Identical to each other.** The archive carries one line name, not a bilingual pair — no Arabic line name exists in the source |
| `fact_ridership_monthly.passenger_trips` | `trips` | |
| `fact_ridership_monthly.station_id` / `route_id` | `entity_name`, per grain | `NULL` for the other grain |

---

## Document corpus — 50 documents

| Kind | Count | Grounded in |
|---|---:|---|
| Dataset dictionaries | 19 | bronze manifests + DQ reports |
| Line guides (EN + AR) | 12 | `dim_station` |
| Fare zone guides | 7 | `dim_station` + `config/fares.yaml` |
| Mode overviews | 4 | `dim_route`, `dim_station`, `fact_ridership_monthly` |
| Fare reference (EN + AR) | 3 | `config/fares.yaml` |
| Capability and limits | 5 | system design |

**These are generated, not transcribed.** Writing RTA service descriptions from
memory would mean inventing verifiable-looking government content in a system
whose entire claim is traceability. Every document carries `source_url` and
`grounded_in` front-matter naming exactly what produced it.

## Search index — 869 chunks

| Kind | EN | AR |
|---|---:|---:|
| Document chunks | 164 | 32 |
| Row summaries | 529 | 144 |

Row summaries are template-rendered sentences describing gold rows, which is
what lets semantic search reach structured facts. Generated by template, never
by a model.

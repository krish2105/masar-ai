# Masar star schema — the only queryable surface

A curated card, not `information_schema`. Dumping the raw catalogue costs
hundreds of tokens and produces *worse* SQL: the model spends attention on
column types it does not need and misses the semantics it does. Everything
below is here because generating correct SQL requires it.

Postgres 16. Read-only role, 5-second statement timeout, forced `LIMIT`.

---

## fact_ridership_monthly
Monthly passenger trips. **The grain differs by mode** — filter on `grain`,
never infer it from `mode`.

| column | type | notes |
|---|---|---|
| `date_key` | TEXT | `YYYYMM`, sortable, joins `dim_date` |
| `year` | INT | |
| `month_num` | INT | 1–12 |
| `mode` | TEXT | `Bus`, `Metro`, `Tram`, `Marine` |
| `grain` | TEXT | `route` (Bus) or `station` (Metro/Tram/Marine) |
| `entity_name` | TEXT | route number, or station name, per `grain` |
| `trips` | DOUBLE | passenger trips in that period |
| `scale_anomaly` | BOOLEAN | **see below** |
| `period_scale_ratio` | DOUBLE | period median ÷ mode baseline |

⚠️ **`scale_anomaly` is not optional.** Some archived periods report a
different unit or reporting period from the rest of their series — metro
2025–26 captures are ~20× smaller than 2021–22 for the same 53 stations.
Summing across that boundary produces a confidently wrong trend.

- Any query about a **trend, total, or comparison across periods** MUST include
  `AND NOT scale_anomaly`.
- A query about **ranking within a single period** may include them (relative
  order holds even when the unit is unknown).

## fact_modal_split_monthly
Trips by transport type per month.

| column | type | notes |
|---|---|---|
| `date_key` | TEXT | `YYYYMM` |
| `year` | INT | |
| `transport_type` | TEXT | `Bus`, `Metro`, `Tram`, `Marine` |
| `trips` | DOUBLE | |

## dim_station
Station master across modes. **`station_id` is unique only within a mode** —
join on `station_key`.

| column | type | notes |
|---|---|---|
| `station_key` | TEXT PK | `{mode}_{station_id}` |
| `station_name_en` | TEXT | e.g. `Union  Metro Station` (note: double spaces occur) |
| `station_name_ar` | TEXT | display form |
| `station_name_ar_norm` | TEXT | search form — match Arabic against **this** |
| `mode` | TEXT | `Metro`, `Tram`, `Bus`, `Marine` |
| `line_name` | TEXT | e.g. `Red Metro line` |
| `zone_id` | INT | **fare zone — drives fare calculation** |
| `latitude`, `longitude` | DOUBLE | WGS84 |

Names are inconsistent (`Union - Red Line`, `Union  Metro Station`). Use
`ILIKE '%...%'` or `similarity()`, never `=`.

## dim_stop
Bus stop master, 4,319 rows.

`stop_id` (PK), `stop_name_en`, `mode`, `street_name`, `latitude`, `longitude`

## dim_route
`route_key` (PK), `route_number`, `route_name_en`, `mode`, `route_type`,
`origin_en`, `destination_en`, `operator`, `route_length_km`, `stop_count`

`route_number` is the public identifier: `13`, `F27`, `X28`, `Red Metro Line`.

## bridge_route_stop
Route ↔ stop with ordering. The join backbone for connection questions.

`route_key`, `route_number`, `mode`, `stop_id`, `stop_name_en`, `stop_order`,
`direction`, `latitude`, `longitude`

## dim_date
`date_key` (PK, `YYYYMM`), `full_date`, `year`, `month`, `month_name_en`,
`month_name_ar`, `quarter`, `year_month`

## dim_salik_tariff
`date_key` (PK), `year`, `fare_aed`

---

## Provenance columns

Every table carries `source_dataset`, `source_url`, `captured_at`,
`source_tier`, `is_synthetic`. Select `source_dataset` and `captured_at` when
the answer will be cited — which is always.

---

## Rules

1. `SELECT` only. No DDL, DML, or multiple statements.
2. Always `LIMIT`; 1000 is forced if you omit it.
3. Join stations on `station_key`, routes on `route_key`.
4. Match names with `ILIKE`/`similarity()`, never `=`.
5. Match Arabic against `station_name_ar_norm`.
6. Exclude `scale_anomaly` rows from any cross-period aggregate.
7. Return `source_dataset` and `captured_at` alongside the answer columns.

## Worked examples

```sql
-- Busiest metro stations in the most recent comparable month
SELECT entity_name, trips, source_dataset, captured_at
FROM fact_ridership_monthly
WHERE mode = 'Metro' AND grain = 'station' AND NOT scale_anomaly
  AND date_key = (
    SELECT MAX(date_key) FROM fact_ridership_monthly
    WHERE mode = 'Metro' AND NOT scale_anomaly
  )
ORDER BY trips DESC
LIMIT 10;
```

```sql
-- Fare zone for a station named loosely
SELECT station_name_en, station_name_ar, zone_id, line_name, source_dataset, captured_at
FROM dim_station
WHERE mode = 'Metro' AND station_name_en ILIKE '%union%'
LIMIT 5;
```

```sql
-- Routes serving both of two stops
SELECT DISTINCT a.route_number, a.mode
FROM bridge_route_stop a
JOIN bridge_route_stop b ON a.route_key = b.route_key
WHERE a.stop_name_en ILIKE '%qusais%' AND b.stop_name_en ILIKE '%business bay%'
LIMIT 20;
```

```sql
-- Metro ridership trend by year, comparable periods only
SELECT year, SUM(trips)::bigint AS total_trips
FROM fact_ridership_monthly
WHERE mode = 'Metro' AND NOT scale_anomaly
GROUP BY year
ORDER BY year;
```

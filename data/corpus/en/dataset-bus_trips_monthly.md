---
doc_id: dataset-bus_trips_monthly
title: 'Dataset: bus_trips_monthly'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_passengers_trips_by_route_monthly-open
retrieved_date: '2026-07-24'
grounded_in:
- bronze manifest for bus_trips_monthly
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: bus_trips_monthly
domain: bus
---


# bus_trips_monthly

**Role in Masar AI.** Monthly passenger trips per bus route — the core trend fact for NETWORK_ANALYTICS.

## Provenance

- Original Dubai Pulse dataset: `rta_bus_passengers_trips_by_route_monthly-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_passengers_trips_by_route_monthly-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 33
- Total size: 176,700 bytes
- Archive capture dates: 2022-07-28 to 2026-01-08
- Data period covered: **2020-12-20 to 2025-09-20**

## Data quality

- Rows read: 6,630
- Rows after typing, deduplication and validation: 6,004
- Duplicate rows removed: 626
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `year, month, route_name`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `year` | String | 0.0% | 6 | 2025 |
| `month` | String | 0.0% | 12 | May |
| `route_name` | String | 0.0% | 258 | X94 |
| `trips` | Float64 | 0.0% | 5,263 | 9022.0 |

---
doc_id: dataset-bus_routes
title: 'Dataset: bus_routes'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_routes-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for bus_routes
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: bus_routes
domain: bus
---


# bus_routes

**Role in Masar AI.** Route master — route number, service type, direction, ordered stop sequence.

## Provenance

- Original Dubai Pulse dataset: `rta_bus_routes-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_routes-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 36,840 bytes
- Archive capture dates: 2022-07-29 to 2022-07-29
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 735
- Rows after typing, deduplication and validation: 487
- Duplicate rows removed: 248
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `route_name, direction, stop_number`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `route_name` | String | 0.0% | 18 | 13 |
| `route_type` | String | 0.0% | 3 | Urban |
| `direction` | String | 0.0% | 27 | GSBS9 -> QSDH11 |
| `stop_name` | String | 94.9% | 21 | Dubai Airport Free Zone Metro Bus Stop 1 |
| `stop_number` | Float64 | 0.0% | 41 | 0.0 |

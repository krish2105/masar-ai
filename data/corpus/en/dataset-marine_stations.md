---
doc_id: dataset-marine_stations
title: 'Dataset: marine_stations'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-marine/rta_marine_stations_gis-open
retrieved_date: '2026-07-24'
grounded_in:
- bronze manifest for marine_stations
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: marine_stations
domain: marine
---


# marine_stations

**Role in Masar AI.** Marine station geometry — abra, ferry, water bus.

## Provenance

- Original Dubai Pulse dataset: `rta_marine_stations_gis-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-marine/rta_marine_stations_gis-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 5,289 bytes
- Archive capture dates: 2022-08-01 to 2022-08-01
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 59
- Rows after typing, deduplication and validation: 59
- Duplicate rows removed: 0
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `station_id` | String | 0.0% | 59 | 27501 |
| `station_name` | String | 0.0% | 57 | Jumeirah Beach Park |
| `route_name` | String | 49.1% | 19 | CR1 |
| `longitude` | Float64 | 0.0% | 28 | 55.29 |
| `latitude` | Float64 | 0.0% | 28 | 25.19 |
| `valida_from` | String | 0.0% | 2 | 2020-01-01 |
| `valida_until` | String | 0.0% | 2 | 2025-01-01 |

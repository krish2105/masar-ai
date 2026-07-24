---
doc_id: dataset-tram_trips_by_station_monthly
title: 'Dataset: tram_trips_by_station_monthly'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-rail/rta_tram_ridership-open
retrieved_date: '2026-07-24'
grounded_in:
- bronze manifest for tram_trips_by_station_monthly
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: tram_trips_by_station_monthly
domain: rail
---


# tram_trips_by_station_monthly

**Role in Masar AI.** Monthly tram trips per station — completes the rail picture beyond metro.

## Provenance

- Original Dubai Pulse dataset: `rta_tram_ridership-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-rail/rta_tram_ridership-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 21
- Total size: 10,446 bytes
- Archive capture dates: 2022-08-01 to 2025-04-25
- Data period covered: **2021-04-20 to 2025-04-22**

## Data quality

- Rows read: 253
- Rows after typing, deduplication and validation: 176
- Duplicate rows removed: 77
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `year, month, tram_station`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `year` | String | 0.0% | 3 | 2025 |
| `month` | String | 0.0% | 12 | Apr |
| `tram_station` | String | 0.0% | 11 | Palm Jumeirah |
| `trips` | Float64 | 0.0% | 169 | 53.0 |

---
doc_id: dataset-metro_trips_by_station_monthly
title: 'Dataset: metro_trips_by_station_monthly'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_ridership-open
retrieved_date: '2026-07-24'
grounded_in:
- bronze manifest for metro_trips_by_station_monthly
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: metro_trips_by_station_monthly
domain: rail
---


# metro_trips_by_station_monthly

**Role in Masar AI.** Monthly passenger trips per metro station — station-level demand, current to Jan 2026.

## Provenance

- Original Dubai Pulse dataset: `rta_metro_ridership-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_ridership-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 36
- Total size: 104,981 bytes
- Archive capture dates: 2022-08-01 to 2026-01-23
- Data period covered: **2021-05-20 to 2026-01-20**

## Data quality

- Rows read: 2,067
- Rows after typing, deduplication and validation: 1,007
- Duplicate rows removed: 1,060
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `year, month, metro_station`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `year` | String | 0.0% | 4 | 2026 |
| `month` | String | 0.0% | 12 | Jan |
| `metro_station` | String | 0.0% | 53 | Airport Terminal 1 Metro Station |
| `trips` | Float64 | 0.0% | 1,007 | 15420.0 |

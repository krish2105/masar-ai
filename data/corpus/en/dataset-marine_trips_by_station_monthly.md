---
doc_id: dataset-marine_trips_by_station_monthly
title: 'Dataset: marine_trips_by_station_monthly'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-marine/rta_marine_ridership-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for marine_trips_by_station_monthly
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: marine_trips_by_station_monthly
domain: marine
---


# marine_trips_by_station_monthly

**Role in Masar AI.** Monthly marine trips per station.

## Provenance

- Original Dubai Pulse dataset: `rta_marine_ridership-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-marine/rta_marine_ridership-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 16
- Total size: 68,323 bytes
- Archive capture dates: 2022-08-01 to 2025-04-15
- Data period covered: **2021-02-20 to 2025-02-20**

## Data quality

- Rows read: 1,057
- Rows after typing, deduplication and validation: 1,057
- Duplicate rows removed: 0
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `year` | String | 0.0% | 4 | 2021 |
| `month` | String | 0.0% | 10 | 3 |
| `marine_mode` | String | 75.4% | 6 | Private_Abra |
| `marine_station` | String | 0.0% | 107 | Waterfront Market Marine Transport Stati |
| `passengers_rids` | String | 5.1% | 333 | 0 |

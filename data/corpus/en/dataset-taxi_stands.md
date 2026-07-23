---
doc_id: dataset-taxi_stands
title: 'Dataset: taxi_stands'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/roads-and-cars/rta_taxi_stand_locations-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for taxi_stands
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: taxi_stands
domain: taxi
---


# taxi_stands

**Role in Masar AI.** Taxi stand geometry — last-mile leg of GEOSPATIAL answers.

## Provenance

- Original Dubai Pulse dataset: `rta_taxi_stand_locations-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/roads-and-cars/rta_taxi_stand_locations-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 8,053 bytes
- Archive capture dates: 2022-06-19 to 2022-06-19
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 147
- Rows after typing, deduplication and validation: 147
- Duplicate rows removed: 0
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `location_name` | String | 0.0% | 147 | Umm suqeim Street |
| `longitude` | Float64 | 0.0% | 35 | 55.22 |
| `latitude` | Float64 | 0.0% | 35 | 25.11 |

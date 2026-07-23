---
doc_id: dataset-taxi_drivers
title: 'Dataset: taxi_drivers'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/roads-and-cars/rta_dubai_taxi_drivers-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for taxi_drivers
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: taxi_drivers
domain: taxi
---


# taxi_drivers

**Role in Masar AI.** Fleet and driver demographics — supply-side analysis.

## Provenance

- Original Dubai Pulse dataset: `rta_dubai_taxi_drivers-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/roads-and-cars/rta_dubai_taxi_drivers-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 18
- Total size: 10,218 bytes
- Archive capture dates: 2022-07-28 to 2024-06-13
- Data period covered: **2021-02-20 to 2024-02-20**

## Data quality

- Rows read: 178
- Rows after typing, deduplication and validation: 135
- Duplicate rows removed: 43
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed

### Warnings

- no natural key declared for 'taxi_drivers'; deduplicated on the full row (43 exact duplicates removed)

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `report_date` | Datetime(time_unit='us', time_zone=None) | 0.0% | 21 | 2022-01-31 00:00:00 |
| `operator_type` | String | 0.0% | 2 | Franchisee |
| `operator_name` | String | 0.0% | 8 | Cars Taxi |
| `drivers_num` | Float64 | 0.0% | 114 | 3040.0 |

---
doc_id: dataset-modal_split_monthly
title: 'Dataset: modal_split_monthly'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-public-transport/rta_public_transport_trips_by_type_of_transport_month-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for modal_split_monthly
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: modal_split_monthly
domain: multimodal
---


# modal_split_monthly

**Role in Masar AI.** Modal split over time — trips by transport type per month.

## Provenance

- Original Dubai Pulse dataset: `rta_public_transport_trips_by_type_of_transport_month-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-public-transport/rta_public_transport_trips_by_type_of_transport_month-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 20
- Total size: 654,702 bytes
- Archive capture dates: 2022-08-01 to 2024-06-15
- Data period covered: **2021-05-20 to 2024-05-20**

## Data quality

- Rows read: 22,894
- Rows after typing, deduplication and validation: 982
- Duplicate rows removed: 21,912
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `year, month, transport_type`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `year` | String | 0.0% | 4 | 2023 |
| `month` | String | 0.0% | 12 | Apr |
| `transport_type` | String | 0.0% | 471 | Bus |
| `trips` | Float64 | 0.0% | 492 | 1889252.0 |

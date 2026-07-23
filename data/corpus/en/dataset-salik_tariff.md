---
doc_id: dataset-salik_tariff
title: 'Dataset: salik_tariff'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-archive/rta_salik_tariff-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for salik_tariff
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: salik_tariff
domain: roads
---


# salik_tariff

**Role in Masar AI.** Salik toll tariff — the drive-vs-transit cost comparison in A11.

## Provenance

- Original Dubai Pulse dataset: `rta_salik_tariff-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-archive/rta_salik_tariff-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 14
- Total size: 1,028 bytes
- Archive capture dates: 2022-08-01 to 2022-08-12
- Data period covered: **2018-12-20 to 2022-01-20**

## Data quality

- Rows read: 36
- Rows after typing, deduplication and validation: 34
- Duplicate rows removed: 2
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `year, month`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `year` | String | 0.0% | 4 | 2018 |
| `month` | String | 0.0% | 12 | Nov |
| `fare` | Float64 | 0.0% | 1 | 4.0 |

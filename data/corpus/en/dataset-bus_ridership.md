---
doc_id: dataset-bus_ridership
title: 'Dataset: bus_ridership'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_ridership-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for bus_ridership
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: bus_ridership
domain: bus
---


# bus_ridership

**Role in Masar AI.** Transaction-grain bus ridership. Sampled — see cap_rationale.

## Provenance

- Original Dubai Pulse dataset: `rta_bus_ridership-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_ridership-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 2
- Total size: 172,956,332 bytes
- Archive capture dates: 2025-04-16 to 2025-04-16
- Data period covered: **2025-04-04 to 2025-04-05**

## Coverage limitation

Only 2 of 31 archived captures were retained (29 skipped).

> Each capture is ~35 MB of transaction-grain records from 2018 and there are 31 of them (~1.0 GB). The analytical signal Masar actually needs is already in bus_trips_monthly at 5 KB per period and current to 2026. Two captures are retained for schema fidelity and to demonstrate handling of large files; the remainder are recorded as skipped in the manifest.

Analysis over this dataset is therefore a **sample**, not the full published history.

## Data quality

- Rows read: 1,595,534
- Rows after typing, deduplication and validation: 1,583,627
- Duplicate rows removed: 11,907
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed

### Warnings

- no natural key declared for 'bus_ridership'; deduplicated on the full row (11907 exact duplicates removed)

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `txn_type` | String | 0.0% | 2 | CKO |
| `txn_date` | Datetime(time_unit='us', time_zone=None) | 0.0% | 2 | 2025-04-04 00:00:00 |
| `txn_time` | String | 0.0% | 79,490 | 11:50:39 |
| `start_location` | String | 0.0% | 2,519 | Reef Mall 2 |
| `end_location` | String | 0.0% | 2,519 | Reef Mall 2 |
| `route_name` | String | 14.2% | 143 | 43 |
| `start_zone` | String | 0.0% | 8 | Zone 5 |
| `end_zone` | String | 0.0% | 8 | Zone 5 |

---
doc_id: dataset-metro_ridership
title: 'Dataset: metro_ridership'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_ridership-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for metro_ridership
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: metro_ridership
domain: rail
---


# metro_ridership

**Role in Masar AI.** Transaction-grain metro ridership. Sampled — see cap_rationale.

## Provenance

- Original Dubai Pulse dataset: `rta_metro_ridership-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_ridership-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 74,743,087 bytes
- Archive capture dates: 2026-01-16 to 2026-01-16
- Data period covered: **2025-03-08 to 2025-03-08**

## Coverage limitation

Only 1 of 24 archived captures were retained (23 skipped).

> Each capture is ~194 MB and there are 24 of them (~4.4 GB) — the single largest item in the catalogue by two orders of magnitude. metro_trips_by_station_monthly carries the same station-level demand signal at 2.7 KB per period, current to January 2026. One capture is retained so the raw grain is inspectable; 23 are recorded as skipped.

Analysis over this dataset is therefore a **sample**, not the full published history.

## Data quality

- Rows read: 657,808
- Rows after typing, deduplication and validation: 580,129
- Duplicate rows removed: 77,679
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed

### Warnings

- no natural key declared for 'metro_ridership'; deduplicated on the full row (77679 exact duplicates removed)

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `txn_type` | String | 0.0% | 2 | Check out |
| `txn_date` | Datetime(time_unit='us', time_zone=None) | 0.0% | 2 | 2025-03-08 00:00:00 |
| `txn_time` | String | 0.0% | 68,246 | 22:56:38 |
| `start_location` | String | 55.3% | 54 | Sharaf DG Metro Station |
| `end_location` | String | 0.0% | 53 | Abu Baker Al Siddique Metro Station |
| `line_name` | String | 0.0% | 2 | Green Metro Line |
| `start_zone` | String | 0.0% | 6 | Zone 5 |
| `end_zone` | String | 0.0% | 6 | Zone 5 |

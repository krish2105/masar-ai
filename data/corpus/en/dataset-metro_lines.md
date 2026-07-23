---
doc_id: dataset-metro_lines
title: 'Dataset: metro_lines'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_lines-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for metro_lines
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: metro_lines
domain: rail
---


# metro_lines

**Role in Masar AI.** Red/Green line master.

## Provenance

- Original Dubai Pulse dataset: `rta_metro_lines-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_lines-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 103 bytes
- Archive capture dates: 2022-08-01 to 2022-08-01
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 2
- Rows after typing, deduplication and validation: 2
- Duplicate rows removed: 0
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `line_name`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `line_name` | String | 0.0% | 2 | Green Metro Line |
| `line_description` | String | 0.0% | 2 | Green Metro Line |

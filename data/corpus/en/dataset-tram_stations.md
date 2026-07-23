---
doc_id: dataset-tram_stations
title: 'Dataset: tram_stations'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-rail/rta_tram_stations-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for tram_stations
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: tram_stations
domain: rail
---


# tram_stations

**Role in Masar AI.** Tram station master — zone_id, line_name, location_id, geometry.

## Provenance

- Original Dubai Pulse dataset: `rta_tram_stations-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-rail/rta_tram_stations-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 1,489 bytes
- Archive capture dates: 2022-08-01 to 2022-08-01
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 11
- Rows after typing, deduplication and validation: 11
- Duplicate rows removed: 0
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `location_id`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `location_id` | String | 0.0% | 11 | 214 |
| `zone_id` | String | 0.0% | 1 | 2 |
| `location_name_en` | String | 0.0% | 11 | Jumeirah Beach Residence 1 |
| `location_name_ar` | String | 0.0% | 11 | أبراج شاطئ جميرا 1 |
| `line_name` | String | 0.0% | 1 | Tram line |
| `longitude` | Float64 | 0.0% | 11 | 55.138232 |
| `latitude` | Float64 | 0.0% | 11 | 25.079737 |
| `station_opening_date` | Datetime(time_unit='us', time_zone=None) | 0.0% | 1 | 2014-11-11 00:00:00 |
| `station_closing_date` | String | 100.0% | 1 |  |
| `location_name_ar_norm` | String | 0.0% | 11 | ابراج شاطي جميرا 1 |

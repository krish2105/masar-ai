---
doc_id: dataset-metro_stations
title: 'Dataset: metro_stations'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_stations_gis-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for metro_stations
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: metro_stations
domain: rail
---


# metro_stations

**Role in Masar AI.** Station master — bilingual names, zone_id, lat/lon, opening date. The single richest table in the catalogue: it alone supports geospatial, fare-zone and Arabic-retrieval requirements.

## Provenance

- Original Dubai Pulse dataset: `rta_metro_stations_gis-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-rail/rta_metro_stations_gis-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 7,435 bytes
- Archive capture dates: 2022-08-01 to 2022-08-01
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 56
- Rows after typing, deduplication and validation: 55
- Duplicate rows removed: 0
- Rows quarantined: 1
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `location_id`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `location_id` | String | 0.0% | 55 | 128 |
| `zone_id` | String | 0.0% | 5 | 5 |
| `location_name_en` | String | 0.0% | 54 | Rashidiya Metro Station |
| `location_name_ar` | String | 0.0% | 55 | الراشدية |
| `line_name` | String | 0.0% | 2 | Red Metro line |
| `longitude` | Float64 | 0.0% | 53 | 55.391198 |
| `latitude` | Float64 | 0.0% | 53 | 25.230222 |
| `station_opening_date` | Datetime(time_unit='us', time_zone=None) | 10.9% | 2 | 2009-09-09 00:00:00 |
| `station_closing_date` | String | 100.0% | 1 |  |
| `location_name_ar_norm` | String | 0.0% | 55 | الراشديه |

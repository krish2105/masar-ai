---
doc_id: dataset-transport_stations
title: 'Dataset: transport_stations'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-public-transport/rta_public_transportation_stations-open
retrieved_date: '2026-07-24'
grounded_in:
- bronze manifest for transport_stations
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: transport_stations
domain: multimodal
---


# transport_stations

**Role in Masar AI.** Unified station master across modes.

## Provenance

- Original Dubai Pulse dataset: `rta_public_transportation_stations-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-public-transport/rta_public_transportation_stations-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 48,393 bytes
- Archive capture dates: 2022-06-19 to 2022-06-19
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 137
- Rows after typing, deduplication and validation: 137
- Duplicate rows removed: 0
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed

### Warnings

- column 'station_number' looks numeric but only 50/137 values parse (36.5%); left as text — it is an identifier, not a measure

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `transport_mode` | String | 0.0% | 4 | Marine |
| `station_name_en` | String | 0.0% | 136 | Jebel Ali Golf Club Marine Transport Sta |
| `station_name_ar` | String | 0.7% | 136 | محطة فندق ومنتجع جبل علي للنقل البحري |
| `station_number` | String | 0.0% | 137 | 27901 |
| `station_location_type_en` | String | 51.8% | 4 | Underground |
| `station_location_type_ar` | String | 51.8% | 4 | تحت الأرض |
| `current_service_status` | String | 35.8% | 5 | NO |
| `number_stops` | Float64 | 36.5% | 10 | 1.0 |
| `number_layby` | Float64 | 84.7% | 10 | 3.0 |
| `customer_facilities` | String | 50.4% | 4 | WIFI, Restrooms, Waiting Area, Air-condi |
| `parking_facilities` | String | 63.5% | 3 | NO |
| `zone_id` | String | 0.0% | 7 | 2 |
| `line_name` | String | 21.2% | 42 | Green |
| `longitude` | Float64 | 0.0% | 134 | 55.02358 |
| `latitude` | Float64 | 0.0% | 134 | 24.98897 |
| `station_opening_date` | Datetime(time_unit='us', time_zone=None) | 56.2% | 12 | 2011-09-09 00:00:00 |
| `station_closing_date` | String | 100.0% | 1 |  |
| `station_starttime_saturday` | String | 25.6% | 13 | 05:30 AM |
| `station_endtime_saturday` | String | 25.6% | 11 | 12:00 AM |
| `station_starttime_sunday` | String | 25.6% | 11 | 05:30 AM |
| `station_endtime_sunday` | String | 25.6% | 10 | 12:00 AM |
| `station_starttime_monday` | String | 25.6% | 11 | 05:30 AM |
| `station_endtime_monday` | String | 25.6% | 10 | 12:00 AM |
| `station_starttime_tuesday` | String | 25.6% | 11 | 05:30 AM |
| `station_endtime_tuesday` | String | 25.6% | 10 | 12:00 AM |
| `station_starttime_wednesday` | String | 25.6% | 11 | 05:30 AM |
| `station_endtime_wednesday` | String | 25.6% | 10 | 12:00 AM |
| `station_starttime_thursday` | String | 25.6% | 11 | 05:30 AM |
| `station_endtime_thursday` | String | 25.6% | 9 | 01:00 AM |
| `station_starttime_friday` | String | 25.6% | 9 | 10:00 AM |
| `station_endtime_friday` | String | 25.6% | 8 | 01:00 AM |
| `station_name_ar_norm` | String | 0.7% | 136 | محطه فندق ومنتجع جبل علي للنقل البحري |
| `station_location_type_ar_norm` | String | 51.8% | 4 | تحت الارض |

---
doc_id: dataset-routes_stops
title: 'Dataset: routes_stops'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-public-transport/rta_public_transportation_routes_stops-open
retrieved_date: '2026-07-23'
grounded_in:
- bronze manifest for routes_stops
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: routes_stops
domain: multimodal
---


# routes_stops

**Role in Masar AI.** Route↔stop bridge table — the join backbone for multi-modal traversal.

## Provenance

- Original Dubai Pulse dataset: `rta_public_transportation_routes_stops-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-public-transport/rta_public_transportation_routes_stops-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 3,652,143 bytes
- Archive capture dates: 2022-06-19 to 2022-06-19
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 18,382
- Rows after typing, deduplication and validation: 18,382
- Duplicate rows removed: 0
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `route_name, route_direction, stop_id, stop_order_number`

### Warnings

- 7100 rows have no coordinates; retained (geometry is optional)

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `report_date` | Datetime(time_unit='us', time_zone=None) | 0.0% | 2 | 2021-12-31 00:00:00 |
| `transport_mode` | String | 0.0% | 4 | Metro |
| `route_name` | String | 0.0% | 231 | Green |
| `route_type` | String | 0.0% | 9 | 0 |
| `route_stops` | String | 0.0% | 64 | 20 |
| `route_direction` | String | 0.0% | 2 | 1 |
| `first_stop` | String | 0.0% | 343 | Etisalat |
| `last_stop` | String | 16.1% | 323 | Creek |
| `depot_name` | String | 26.1% | 23 | Al Qusais |
| `route_frequency` | Float64 | 26.2% | 60 | 7.0 |
| `route_number_of_services` | String | 35.5% | 87 | 17 |
| `stop_order_number` | Float64 | 26.1% | 78 | 11.0 |
| `stop_name` | String | 26.1% | 3,009 | Etisalat |
| `stop_id` | String | 0.2% | 2,734 | G11 |
| `route_length` | Float64 | 38.3% | 1,722 | 22.0 |
| `operated_days` | String | 39.1% | 8 | 1 |
| `operated_hours` | String | 42.1% | 24 | 17 |
| `street_name` | String | 46.3% | 282 | D50 |
| `longitude` | Float64 | 38.6% | 2,707 | 55.401007 |
| `latitude` | Float64 | 38.6% | 2,705 | 25.254805 |
| `bus_stop_type` | String | 79.5% | 7 | Nornal - Pole |
| `time_table_panel` | String | 39.1% | 3 | Yes |
| `mupi_available` | String | 39.1% | 3 | No |
| `rtpi_available` | String | 39.4% | 3 | No |
| `last_survey_date` | Datetime(time_unit='us', time_zone=None) | 79.5% | 2 | 2020-04-02 00:00:00 |

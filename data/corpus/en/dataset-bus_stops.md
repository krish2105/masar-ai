---
doc_id: dataset-bus_stops
title: 'Dataset: bus_stops'
lang: en
service_category: data_dictionary
source_url: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_stops_gis-open
retrieved_date: '2026-07-24'
grounded_in:
- bronze manifest for bus_stops
- data quality report
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
dataset_id: bus_stops
domain: bus
---


# bus_stops

**Role in Masar AI.** Stop master with geometry — powers catchment and nearest-stop analysis (A10).

## Provenance

- Original Dubai Pulse dataset: `rta_bus_stops_gis-open`
- Original landing page: https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_stops_gis-open
- Recovered from: public Internet Archive snapshots of Dubai Pulse
- Files recovered: 1
- Total size: 22,758,950 bytes
- Archive capture dates: 2022-07-29 to 2022-07-29
- Data period: static reference table (no time dimension)

## Data quality

- Rows read: 182,466
- Rows after typing, deduplication and validation: 4,319
- Duplicate rows removed: 178,147
- Rows quarantined: 0
- Coercion failures: 0
- Quality gate: passed
- Deduplicated on: `stop_id`

## Columns

| column | type | null rate | distinct | example |
|---|---|---|---|---|
| `report_date` | Datetime(time_unit='us', time_zone=None) | 0.0% | 22 | 2022-07-25 00:00:00 |
| `stop_name` | String | 0.0% | 3,090 | 2nd Zaabel Rd 1 |
| `stop_id` | String | 0.0% | 4,319 | 2575 |
| `street_name` | String | 82.6% | 300 | Al awer road |
| `route_name` | String | 0.0% | 220 | 10 |
| `longitude` | Float64 | 0.0% | 3,999 | 55.29433 |
| `latitude` | Float64 | 0.0% | 3,692 | 25.224061 |
| `bus_stop_type` | String | 99.3% | 3 | AC Shelter |
| `time_table_panel` | String | 0.0% | 1 | Yes |
| `mupi_available` | String | 80.8% | 3 | Yes |
| `rtpi_available` | String | 80.8% | 4 | No |
| `last_survey_date` | Datetime(time_unit='us', time_zone=None) | 80.8% | 112 | 2018-07-19 00:00:00 |
| `valid_from` | Datetime(time_unit='us', time_zone=None) | 0.0% | 56 | 2022-05-02 00:00:00 |
| `valid_until` | Datetime(time_unit='us', time_zone=None) | 0.0% | 1 | 2036-01-01 00:00:00 |

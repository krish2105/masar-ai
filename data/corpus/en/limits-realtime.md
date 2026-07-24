---
doc_id: limits-realtime
title: Real-time transport data availability
lang: en
service_category: capability
source_url: https://github.com/krish2105
retrieved_date: '2026-07-24'
grounded_in:
- system design
- docs/DECISIONS.md
generated: true
disclaimer: Generated from data Masar AI holds. Independent academic project; not
  affiliated with or endorsed by RTA.
---

# Real-time data is not available

RTA does **not** publish real-time vehicle positions, live arrival predictions, or service disruption feeds as open data. Masar AI therefore cannot answer:

- Where is bus route 13 right now?
- When is the next metro at Union?
- Is there a delay on the Red Line today?

What Masar can do instead is reason from **network topology and published schedules**: which routes serve a stop, how many interchanges a journey needs, how far apart two stops are, and how ridership has behaved historically.

Masar never simulates live data. When asked a real-time question it says the data is not publicly available and offers the schedule-based alternative.

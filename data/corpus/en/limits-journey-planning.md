---
doc_id: limits-journey-planning
title: How journey reasoning works
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

# Journey reasoning

Masar is **not a journey planner** and does not attempt to be one. It has no timetable data, no live positions, and no routing engine.

What it does have is the route-to-stop network. From that it can determine which routes serve a given stop, whether two stops share a route, roughly how far apart points are (great-circle distance), and how many interchanges a journey would need.

It reports **distance and interchange count**. It never invents a journey duration, because it has no data from which one could be derived. For an actual journey plan with times, use RTA's own S'hail app or rta.ae.

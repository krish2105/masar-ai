---
doc_id: limits-data-currency
title: How current is the data?
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

# Data currency

Masar AI's source data comes from public Internet Archive snapshots of the Dubai Pulse open data platform, which was retired and now redirects to a portal whose catalogue requires authentication.

Consequences a user should know:

1. **Every figure has a capture date**, shown on its citation. A figure is accurate as of that date, not today.
2. **Recency varies sharply by dataset.** Metro station ridership runs to January 2026; the Salik tariff table stops in 2022.
3. **Some series are not internally comparable.** Where a dataset's later captures use a different unit or reporting period from its earlier ones, those periods are flagged and excluded from trend calculations, and the limitation is stated in the answer rather than hidden.

Masar is an independent academic project and is not affiliated with, endorsed by, or connected to RTA.

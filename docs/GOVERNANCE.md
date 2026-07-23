# Governance

## Affiliation

**Masar AI is an independent academic project. It is not affiliated with,
endorsed by, or connected to the Roads and Transport Authority.**

This appears in the README, the UI footer of every page, the API description,
and the front-matter of every generated corpus document. It is not a
disclaimer bolted on at the end; it is stated wherever the system speaks.

## Where the data comes from

The build specification assumed data would be downloaded from Dubai Pulse. That
platform has been retired.

| Check | Result |
|---|---|
| `www.dubaipulse.gov.ae/data/...` | 301 → `https://data.dubai` (homepage, not the dataset) |
| `api.dubaipulse.gov.ae/open/rta/...` | Alive, `401 Unauthorized application request` |
| `data.dubai` catalogue | JS portal behind a Login / Portal Access gate |
| `opendata.dubai.gov.ae`, `data.gov.ae`, `opendata.rta.ae` | Dead |

Masar's source data is therefore recovered from **public Internet Archive
snapshots of Dubai Pulse's CKAN resource downloads**. See
[ADR-001](DECISIONS.md).

### What that means, stated plainly

1. **The data is archived, not live.** Every row carries `captured_at`, and
   every evidence card in the UI displays the capture date rather than today's
   date.
2. **Recency varies sharply by dataset.** Metro station ridership runs to
   January 2026; the Salik tariff stops in 2022. The `/data` page publishes the
   period range per dataset.
3. **Masar is one step removed from RTA.** It reads what RTA published, as the
   Internet Archive captured it. It has no connection to any RTA system.

### Terms of use

The underlying data was published by RTA via Dubai Pulse as open data under
that platform's terms. The Internet Archive redistributes publicly accessible
pages under its own terms. This project uses the data for non-commercial
academic purposes, with attribution to RTA as publisher on every citation.

Requests to the Archive are rate-limited, retried with backoff, and sent with a
descriptive User-Agent identifying the project. Nothing behind an
authentication gate was accessed.

## Data quality controls

Every dataset produces a report in `reports/dq/` recording rows in, rows out,
duplicates removed, rows quarantined, coercion failures, per-column null rates,
and warnings. The `/data` page renders these.

**Current state: 19/19 datasets pass, zero coercion failures, 2,196,751 silver
rows.**

### Three quality problems found and handled

**1. Upstream corruption in the modal-split dataset.** Several archived
captures publish 6-character truncated operator names (`"Renaul"`, `"Rehabi"`,
`"City C"`) in the `transport_type` column — one file carries 18,768 rows where
a modal split has about five. A closed-domain validation drops them: 982 rows →
51 valid. Rejections are counted and logged.

**2. A non-comparable ridership series.** Metro captures from 2025–26 report
values roughly 20× smaller than 2021–22 for the *same 53 stations*. A 20% drop
in Dubai Metro ridership did not happen; the later captures use a different unit
or reporting period, which the published schema does not state.

No conversion factor was invented. Instead every fact row carries
`period_scale_ratio` and `scale_anomaly`, the column comment instructs the
Text-to-SQL agent to exclude flagged rows from any cross-period aggregate, and
the analytics dashboard states the exclusion beneath every chart. The metro
trend is then internally consistent (2021: 140M, 2022: 143M).

**3. An identifier destroyed by type coercion.** `station_number` holds
alphanumeric codes such as `ABBS`; a name-based rule coerced it to a float and
nulled 87 station identifiers. Numeric casting is now decided by probing the
values, not by reading the column name.

## Coverage limits, published rather than hidden

Two transaction-grain families were capped because their size is out of
proportion to their analytical value:

| Dataset | Available | Retained | Why |
|---|---|---|---|
| `metro_ridership` | 24 files (~4.4 GB) | 1 | `metro_trips_by_station_monthly` carries the same station demand signal at 2.7 KB per period and is *more* current |
| `bus_ridership` | 31 files (~1.0 GB) | 2 | `bus_trips_monthly` covers the same ground at 5 KB per period |

Every cap is reported: `Dataset.cap_rationale` in prose, `coverage.capped` in
the bronze manifest with available/retained/dropped counts, `(capped 1/24)` in
the Phase 1 gate output, and a badge on the `/data` page. **A cap that is not
surfaced reads as full coverage when it is not.**

One dataset could not be recovered at all: `rta_salik_tolling_gates_location`
has no CSV capture in the Archive. `dim_salik_gate` is created empty so queries
return no rows — a truthful answer — rather than "relation does not exist".

## Where numbers come from

All arithmetic is deterministic Python (`agents/a11_calculator.py`), computed in
`Decimal` and rounded once. A13 is instructed to quote calculator output
verbatim and is forbidden from recomputing. Numeric accuracy is therefore a
property of the code, verified by unit tests, not a metric that can drift.

Rates live in `config/fares.yaml`, each with a `source`, an `effective_from`
date, and a `verified_against_dataset` flag. Two honest consequences:

- **Salik** is AED 4.00 per crossing, effective 2018-11, verified against the
  archived tariff dataset. RTA later introduced variable peak pricing, which is
  in no dataset Masar holds — so every Salik answer states the effective date
  and notes that a present-day peak crossing costs more.
- **nol fare bands** appear in no archived dataset at all. They are marked
  `verified_against_dataset: false`, every answer using them says the figure is
  indicative, and the evidence card carries a warning badge.

## Privacy

Masar holds **no personal data**. The datasets are aggregate network and service
data. There are no user accounts, no authentication, and no PII storage, which
keeps the project outside UAE PDPL obligations entirely rather than trying to
satisfy them.

The Guardrail agent blocks requests for personal information about individuals
and requests to perform transactions, in both cases with a redirect explaining
why rather than a bare refusal.

Session identifiers are random UUIDs held in memory for the life of a
conversation. Traces record agent behaviour and the query text, never a user
identity.

## Free-tier inference and data handling

Free LLM tiers are typically funded by using submitted prompts as training data.
That is acceptable here because no query touches confidential or personal data —
every question is about public transport. **It would not be acceptable in
production**, where the correct posture is paid endpoints or self-hosted models
in a UAE-resident region.

The local-first design means the system runs with **no data leaving the machine
at all** when only Ollama is configured.

## What the system will not do

- Claim knowledge of real-time vehicle positions or disruptions. RTA publishes
  no such open data, and A1 says so rather than guessing.
- State a journey duration. Masar holds no timetables or speeds, so any duration
  would be fabricated. It reports distance and interchange count.
- Present a claim it cannot source. A13 strips unresolvable citation markers in
  code, because a marker pointing at nothing looks like evidence.
- Perform transactions, or appear willing to.

## Auditability

Every turn writes a full trace to `traces/{session}/{turn}.jsonl` and to the
`agent_traces` table: each hop's agent, model, provider, tokens, latency,
decision and cycle. `/trace/{id}` renders it and exports JSON.

A reader can watch the Grader return control to the Planner with named gaps,
compare the revised plan to the failed one, and check that the citation on a
number resolves to a real row. A system that cannot be audited that way is
asking to be taken on trust.

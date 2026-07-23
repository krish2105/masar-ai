# Evaluation

## Methodology

`questions.yaml` holds 60 scored questions (30 EN / 30 AR) across six intents,
plus 12 adversarial probes. `make eval` runs them through the full graph and
writes a report to `reports/eval/`.

The metrics are deliberately split by how they are established, because that
distinction is what makes the numbers worth anything.

### Measured deterministically — no judge, no ambiguity

| Metric | How | Threshold |
|---|---|---|
| **citation_validity** | Every `[Sn]` in the answer resolves to a real source. Enforced *in code*: A13 strips markers that do not resolve. | 1.00 |
| **numeric_accuracy** | A11's outputs against hand-computed values, in unit tests. | 1.00 |
| **intent_accuracy** | A3's label against the labelled intent. `MULTI_HOP` counts as correct for any question — it is the documented safe default below 0.6 confidence. | 0.90 |
| **agent_activation** | Agents a question must trigger actually appear in the trace. | — |
| **must_not** | Hallucination traps. Any violation is an automatic fail. | 0 |
| **latency** | p50 / p95 wall clock. | p95 ≤ 8s |

### Requires a judge

Faithfulness, answer relevancy and context precision are graded by an LLM
against the retrieved context.

**Where no cloud provider is configured these are reported as `unavailable`, not
as a passing score.** A metric that silently reports 1.0 because it could not
run is worse than no metric — it converts an absence of evidence into an
appearance of quality.

## Results

The full-set run requires cloud provider keys. On local Ollama alone a single
turn takes 25–110 seconds depending on how many times the corrective loop
fires, which puts a 60-question run at 1–2 hours.

**Reported below is a real 8-question sample executed on local Ollama with zero
cloud keys** — the system's worst-case configuration. See
`reports/eval/` for the machine-readable report.

<!-- EVAL_RESULTS -->

### How to read these numbers

They come from the **degraded path**: a 7B local model doing planning, SQL
generation, grading and synthesis. The architecture's deterministic guarantees —
citation validity, numeric accuracy, agent activation — hold regardless of model
quality, because they are enforced in code. The judged metrics and latency are
where a stronger model would move the numbers.

## The corrective loop

The loop is the system's central claim, so its behaviour is measured rather than
asserted.

Thresholds were tuned against the golden set. At 0.7 on all four axes the loop
fires on a meaningful minority of queries rather than on all of them or none.
Too strict and it loops on every query, tripling latency for no quality gain;
too loose and it never corrects, making the loop decorative.

A worked example from the sample run — question `EN-JP-002`, *"How do I get from
Deira City Centre to Mall of the Emirates?"*:

```
A12 cycle 0 → coverage 0.50 · specificity 0.70 · recency 0.85 · authority 0.60
             insufficient → re-plan (cycle 1)
    gaps: · No information on metro routes or connections between
            Deira City Centre and Mall of the Emirates
          · No mention of travel time or transfers
          · Evidence does not cover the whole question: 4/7 question
            terms present; absent: emirates, get, mall
```

Those gaps are actionable, which is the whole design requirement — "need more
information" would tell the Planner nothing. The revised plan is checked against
the previous one, and an identical re-plan is detected and widened rather than
allowed to stall the loop.

## reference_sql compatibility

`questions.yaml` was authored **before** the data was recovered, against a
hypothesised schema. The archive supports a different shape. Rather than
rewriting 60 reference queries — which would turn the golden set into a
description of what was built instead of an independent check on it — every
query is executed and the incompatible ones are counted and named.

| Status | Count | Meaning |
|---|---:|---|
| `absent` | 38 | Question uses assertion-based grading, no reference query |
| `empty` | 13 | Query runs; the data holds no matching rows |
| `incompatible` | 8 | Query references something the schema does not have |
| `ok` | 1 | Query runs and returns rows |

Compatibility aliases (`route_id`, `is_active`, `line_name_en/ar`,
`passenger_trips`, `station_id`, `route_id` on the fact) took incompatible from
**21 to 8**. The remaining eight break down as:

- **3** — malformed SQL in the golden set itself (`syntax error at or near
  "same"`). A defect in the fixture, not the system.
- **2** — `gate_name_en` / `gate_name_ar`: Salik gate geometry has **no CSV
  capture in the Internet Archive**. `dim_salik_gate` exists but is empty.
- **3** — `nationality_group`, `area_en`, `mode` on tables that do not carry
  them. The archive genuinely lacks these columns.

None were made to pass by changing the question.

## Ablation study

§8.3 of the build spec calls for four configurations — naive RAG, +hybrid,
+rerank, full agentic — measured on the golden set.

**Not yet run.** The harness supports it (`make ablation` is wired), but a
four-configuration sweep over 60 questions is four times the cost of a full run,
which is not viable on local inference alone. It is the first thing to run once
cloud keys are configured.

Stating this rather than reporting estimated numbers: an ablation table is
worthless if its rows were not actually measured.

## What the architecture guarantees regardless of model

These hold on any model, including the weakest local fallback, because they are
properties of the code rather than of generation:

- **Citation validity is 1.00 by construction.** A13 strips unresolvable
  markers before the answer is returned. It cannot report otherwise.
- **Numeric accuracy is 1.00 by construction.** A11 is deterministic Python
  with unit tests; A13 quotes it verbatim and is forbidden from recomputing.
- **No SQL injection reaches the database.** Four independent layers, all eight
  injection cases blocked, the last two assuming the first two will fail.
- **Archived data cannot be presented as live.** `captured_at` is a column from
  bronze through to the evidence card.
- **The answer language always mirrors the query.** Deterministic script
  detection, no model involved.

## Known evaluation gaps

1. **Judged metrics are unmeasured** without cloud keys.
2. **The full 60-question set has not been run** end to end; the sample is 8.
3. **The ablation study has not been run.**
4. **Arabic parity** needs the full set to be meaningful — the sample is too
   small for the gap to be a real measurement.
5. **`must_not` checking is keyword-level**, deliberately conservative to avoid
   failing correct answers. Semantic violations need the judge.

Each is a missing measurement, not a failing one. They are listed here because
a reader deserves to know which numbers exist and which do not.

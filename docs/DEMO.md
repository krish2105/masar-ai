# Three-minute demo script

The goal is not to show that it answers questions. Every RAG demo answers
questions. The goal is to show the three things that are actually hard:
**it decides how to answer**, **it notices when it was wrong**, and **it refuses
to make things up**.

Run `make up && make dev` first. Have `/` open in one tab and the terminal
visible.

---

## 0:00 — The premise (20 seconds)

> "Dubai's RTA runs one of the densest transit networks in the world, and its
> public assistant is a service catalogue — it routes you to a form. It can't
> tell you whether the bus or the metro is cheaper for your commute, because
> that needs fare rules, station zones, a distance and a ridership trend, and
> which of those you need only becomes clear after you read the question.
>
> This is a decision-intelligence layer over the same open data."

Point at the footer disclaimer while saying it.

> "It's an independent academic project. Not affiliated with RTA — and that's
> stated on every page, not buried in a README."

---

## 0:20 — The re-plan (60 seconds) ← *the money shot*

Type: **"Is bus or metro cheaper from Al Qusais to Business Bay, and which is busier?"**

While it runs, narrate the rail:

> "Fourteen agents. Watch the strip above the composer — that's not decoration,
> it's the actual execution. Guardrail, language detection, intent routing, then
> the Supervisor decomposes the question into sub-tasks and dispatches them in
> parallel: document retrieval, a SQL query against the star schema, a
> geospatial lookup, and a deterministic fare calculation."

When the amber badge appears:

> "**There.** `A12 → A4 re-plan`. The Grader scored the evidence on coverage,
> specificity, recency and source authority, decided it wasn't enough, and sent
> control *back* to the Planner with named gaps. That's a cycle in the graph.
> Classical RAG is a straight line — retrieve, generate, done. It has no way to
> notice it retrieved the wrong thing."

Expand the gaps panel:

> "And the gaps are specific — 'no fare zone found for Al Qusais', not 'need
> more information'. A vague gap tells the Planner nothing."

---

## 1:20 — Citations and arithmetic (40 seconds)

Hover an `[S2]` chip, then point at the evidence panel:

> "Every claim carries a marker that resolves to a real row. If a claim can't be
> sourced, it's deleted — not softened, deleted. That's enforced in code, after
> generation, not by asking the model nicely."

Point at the capture date on a card:

> "Note the date on the card — that's when the data was **captured from the
> archive**, not today. Dubai Pulse was retired mid-project; this data comes
> from Internet Archive snapshots. So every card shows its age, and the system
> is structurally incapable of presenting archived data as live."

Point at a calculated figure:

> "The money figure came from deterministic Python, not the model. Language
> models are unreliable arithmetic engines and fares are correctness-critical,
> so the calculator computes in `Decimal` and the synthesiser is forbidden from
> recomputing — it quotes verbatim."

---

## 2:00 — Refusing to invent (30 seconds)

Click the suggestion: **"Is real-time bus location available?"**

It answers immediately, no retrieval:

> "It doesn't refuse — it explains. RTA publishes no open real-time feed, so the
> honest answer is that the data doesn't exist, plus what it *can* do instead.
> A demo that faked a live position here would be the most impressive thing on
> screen and the least trustworthy."

If time allows, mention:

> "Same principle on journey times. It reports distance and interchange count
> and never invents a duration, because it has no timetables to derive one from."

---

## 2:30 — The receipts (30 seconds)

Click **"view full trace →"**:

> "Every hop: which agent, which model, which provider, tokens, latency, the
> decision it made, and which planning cycle it belonged to. The Grader's four
> sub-scores against the 0.7 threshold. Exportable as JSON."

Then open `/data`:

> "And the provenance ledger — every dataset, rows in versus out, what was
> quarantined, and where coverage was capped and why. One dataset is sampled at
> 1 of 24 captures because the full family is 4.4 GB of transaction records
> whose signal is already in a 2.7 KB monthly aggregate. That cap is *published*
> — a cap you don't surface reads as full coverage when it isn't."

---

## If asked: "why is it slow?"

> "This is running entirely on a local 7B model with zero cloud API keys — the
> worst-case configuration, chosen deliberately for this demo. The router walks
> a fallback chain across Groq, Gemini and Cerebras before dropping to local, and
> flags `degraded_mode` so the UI can badge it. With a free Groq key a turn is
> a few seconds. The interesting engineering is that it degrades *visibly*
> rather than failing or, worse, silently getting weaker."

## If asked: "what would you do next?"

> "Three things. Run the ablation study — the harness is wired but a
> four-configuration sweep isn't viable on local inference. Add a GraphRAG layer,
> because the route–stop–zone network is genuinely a graph and I'm currently
> approximating traversal with SQL joins over a bridge table. And fine-tune the
> reranker on Arabic transit pairs — the corpus is English-dominant and that's
> where the measured parity gap comes from."

---

## Do not

- Claim any live RTA connection or integration.
- Present the Salik rate as current — it's the 2018 flat toll, and the system
  says so.
- Say "we use AI to..." — describe what the system *does*.
- Hide the degraded-mode badge. It's evidence the design works.

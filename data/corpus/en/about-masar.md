---
doc_id: about-masar
title: What Masar AI is
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

# About Masar AI

Masar (مسار, 'route' or 'path') is a decision-intelligence layer over Dubai's published open transport data. It answers multi-step questions that require combining several kinds of evidence — service documentation, ridership facts, geography, and cost arithmetic — in a single answer.

## How it answers

A planning agent decides, per question, which sources to consult. It can run hybrid document retrieval, query the analytical database, compute distances, and run deterministic fare arithmetic — in parallel where the sub-tasks are independent.

A grading agent then scores the assembled evidence on coverage, specificity, recency and source authority. If the evidence is insufficient it names the gaps and sends the question back to be re-planned, up to three times, before answering with an explicit low-confidence caveat.

## Guarantees

- Every factual claim carries a citation resolving to a specific dataset row or document.
- All arithmetic is deterministic Python. Language models never compute numbers in this system.
- Answers are given in the language of the question.
- Where the data cannot support an answer, Masar says so rather than guessing.

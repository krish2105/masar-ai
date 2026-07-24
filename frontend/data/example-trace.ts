/**
 * A pre-rendered example, sourced VERBATIM from a real recorded run in the
 * traces/ archive — not fabricated. A multi-hop question where the Grader (A12)
 * judged the assembled evidence insufficient twice and returned control to the
 * Planner (A4) each time, then answered with low confidence once the 3-cycle cap
 * was reached — rather than inventing facts to fill the gap.
 *
 * It shows the one thing that separates Masar from a linear retrieve-then-
 * generate pipeline, before a visitor types anything. Honesty note: this run
 * used the local fallback model (~152s end to end). Cloud providers (Groq /
 * Gemini) answer the same question in seconds; the reasoning path is identical.
 */
export interface ExampleCycle {
  /** What the Planner decided at the top of this cycle. */
  plan: string;
  /** Tool agents that ran in this cycle (A6 hybrid retrieval, A8 Text-to-SQL). */
  agents: string[];
  /** The Grader's verdict at the end of the cycle. */
  grader: string;
  /** True when the Grader sent control back to the Planner to try again. */
  loops: boolean;
}

export const EXAMPLE_TRACE = {
  intent: "MULTI_HOP",
  /** Agents that ran once, up front, to understand the question. */
  understand: ["A1", "A2", "A3"],
  totalSeconds: 152,
  replanCycles: 2,
  confidence: "low" as const,
  citations: 2,
  cycles: [
    { plan: "planned 4 sub-tasks", agents: ["A8"], grader: "insufficient — 2 named gaps", loops: true },
    { plan: "re-planned · 5 sub-tasks", agents: ["A6", "A8"], grader: "insufficient — 1 named gap", loops: true },
    { plan: "re-planned · 5 sub-tasks", agents: ["A8", "A6"], grader: "cycle cap reached", loops: false },
  ] as ExampleCycle[],
};

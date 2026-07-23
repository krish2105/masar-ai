"""The shared state contract for the 14-agent graph.

Every agent reads and writes this one structure. Making it explicit and typed is
the reason LangGraph was chosen over an opaque ReAct loop: for a system that
must justify its answers, the state at every hop has to be inspectable and
replayable.

`MasarState` is a TypedDict because LangGraph merges partial updates into it.
The nested payloads are Pydantic models so their shapes are validated where
they are produced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

# =============================================================================
# Enumerations
# =============================================================================


class Intent(StrEnum):
    """The seven intents A3 classifies into (§5.3)."""

    JOURNEY_PLANNING = "JOURNEY_PLANNING"
    FARE_COST = "FARE_COST"
    SERVICE_INFO = "SERVICE_INFO"
    NETWORK_ANALYTICS = "NETWORK_ANALYTICS"
    GEOSPATIAL = "GEOSPATIAL"
    MULTI_HOP = "MULTI_HOP"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ToolClass(StrEnum):
    """The five tool classes the Supervisor dispatches across."""

    RETRIEVE = "retrieve"
    SQL = "sql"
    API = "api"
    GEO = "geo"
    CALC = "calc"


class EvidenceType(StrEnum):
    DOCUMENT = "document"  # chunk from the curated corpus
    SQL_RESULT = "sql_result"  # rows from the star schema
    API_RESULT = "api_result"  # Dubai Pulse gateway response
    GEO_RESULT = "geo_result"  # computed distances / catchment
    CALC_RESULT = "calc_result"  # deterministic fare or toll arithmetic


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# Planning
# =============================================================================


class SubTask(BaseModel):
    """One unit of work in the Supervisor's plan."""

    id: str
    description: str
    tool: ToolClass
    depends_on: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    sub_tasks: list[SubTask] = Field(default_factory=list)
    reasoning: str = ""
    expected_evidence_types: list[EvidenceType] = Field(default_factory=list)
    cycle: int = 0
    """Which planning cycle produced this. Cycle 0 is the initial plan; 1+ are
    re-plans triggered by the Grader. Making this visible is what lets the trace
    viewer show the loop firing."""

    addresses_gaps: list[str] = Field(default_factory=list)
    """Gaps named by A12 that this revision is meant to close. A re-plan that
    repeats the failed plan is a bug, and this field is how it is caught."""


# =============================================================================
# Evidence and citations
# =============================================================================


class Source(BaseModel):
    """A resolvable pointer to exactly where a claim came from.

    Every field here ends up on an evidence card in the UI. `captured_at` is
    mandatory because the data is archived rather than live, and presenting it
    without the capture date would misrepresent its currency.
    """

    id: str  # "S1", "S2", …
    type: EvidenceType
    dataset_or_doc: str
    source_url: str
    row_id_or_chunk_id: str | None = None
    captured_at: str | None = None
    source_tier: str = "archive"
    is_synthetic: bool = False
    last_updated: str | None = None


class Evidence(BaseModel):
    """One retrieved item plus its provenance and scoring."""

    content: str
    evidence_type: EvidenceType
    source: Source
    score: float = 0.0
    sub_task_id: str | None = None

    # Retained so the trace can show why an item ranked where it did.
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None


class GradeReport(BaseModel):
    """A12's verdict on the assembled evidence bundle."""

    coverage: float = 0.0
    specificity: float = 0.0
    recency: float = 0.0
    source_authority: float = 0.0

    sufficient: bool = False
    gaps: list[str] = Field(default_factory=list)
    reasoning: str = ""
    cycle: int = 0

    @property
    def scores(self) -> dict[str, float]:
        return {
            "coverage": self.coverage,
            "specificity": self.specificity,
            "recency": self.recency,
            "source_authority": self.source_authority,
        }

    @property
    def weakest_axis(self) -> str:
        return min(self.scores, key=lambda k: self.scores[k])


# =============================================================================
# Observability
# =============================================================================


class TraceHop(BaseModel):
    """One agent execution. A14 emits these on every state transition."""

    agent_id: str
    agent_name: str
    timestamp: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    latency_ms: float = 0.0

    model_used: str | None = None
    provider: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_estimate_usd: float = 0.0
    """Zero on the free tier — shown anyway, because a cost line that only
    appears once it is non-zero is a cost line nobody trusts."""

    decision: str | None = None
    cycle: int = 0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Reducers
# =============================================================================


def append_evidence(left: list[Evidence], right: list[Evidence]) -> list[Evidence]:
    """Accumulate evidence across parallel sub-tasks, de-duplicated by source.

    Parallel branches routinely surface the same row or chunk; keeping the
    higher-scoring copy avoids inflating the Grader's coverage signal with
    duplicates.
    """
    merged: dict[tuple[str, str | None], Evidence] = {}
    for item in [*left, *right]:
        key = (item.source.dataset_or_doc, item.source.row_id_or_chunk_id)
        existing = merged.get(key)
        if existing is None or item.score > existing.score:
            merged[key] = item
    return sorted(merged.values(), key=lambda e: e.score, reverse=True)


def append_hops(left: list[TraceHop], right: list[TraceHop]) -> list[TraceHop]:
    return [*left, *right]


def append_plans(left: list[Plan], right: list[Plan]) -> list[Plan]:
    return [*left, *right]


# =============================================================================
# The state
# =============================================================================


class MasarState(TypedDict, total=False):
    # ---- identity ----------------------------------------------------------
    session_id: str
    turn_id: str
    started_at: str

    # ---- A1 guardrail ------------------------------------------------------
    raw_query: str
    safe: bool
    block_reason: str | None
    sanitized_query: str

    # ---- A2 language -------------------------------------------------------
    language: Literal["en", "ar", "mixed", "unknown"]
    script: str
    normalized_query: str
    transliterated_query: str | None
    response_language: Literal["en", "ar"]

    # ---- A3 intent ---------------------------------------------------------
    intent: Intent
    intent_confidence: float

    # ---- A4 supervisor -----------------------------------------------------
    plan: Plan
    plan_history: Annotated[list[Plan], append_plans]
    cycle: int

    # ---- A5–A11 evidence gathering ----------------------------------------
    query_variants: list[str]
    evidence: Annotated[list[Evidence], append_evidence]
    sub_task_errors: dict[str, str]

    # ---- A12 grader --------------------------------------------------------
    grade: GradeReport
    grade_history: list[GradeReport]

    # ---- A13 synthesis -----------------------------------------------------
    answer: str
    citations: list[Source]
    confidence: Confidence
    assumptions: list[str]

    # ---- A14 observability -------------------------------------------------
    trace: Annotated[list[TraceHop], append_hops]

    # ---- runtime -----------------------------------------------------------
    degraded_mode: bool
    data_freshness: Literal["live", "cached", "archived"]
    cached: bool


def new_state(
    *,
    session_id: str,
    turn_id: str,
    raw_query: str,
) -> MasarState:
    """A fresh state with every accumulator initialised.

    Accumulators must start as empty lists rather than being absent: LangGraph
    reducers are only invoked when a key is already present.
    """
    return MasarState(
        session_id=session_id,
        turn_id=turn_id,
        started_at=datetime.now(tz=UTC).isoformat(),
        raw_query=raw_query,
        safe=True,
        block_reason=None,
        sanitized_query=raw_query,
        cycle=0,
        plan_history=[],
        query_variants=[],
        evidence=[],
        sub_task_errors={},
        grade_history=[],
        citations=[],
        assumptions=[],
        trace=[],
        degraded_mode=False,
        data_freshness="archived",
        cached=False,
    )

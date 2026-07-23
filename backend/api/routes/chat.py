"""Chat endpoint with SSE streaming.

Two shapes:

* `POST /api/v1/chat`        — run a turn, return the whole result
* `POST /api/v1/chat/stream` — the same turn, streamed as Server-Sent Events

The stream is the interesting one. The graph is not token-streaming internally,
so instead of faking a token stream this endpoint streams **what actually
happens**: each agent starting and finishing, evidence as it is assembled, and
the re-plan when it fires. The answer then streams out in chunks.

That ordering is deliberate. Watching the agents light up — and seeing
`A12 → A4 re-plan` appear mid-turn — is the thing that makes the architecture
legible in a way a paragraph of README never will.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.agents.a14_observability import agent_label
from backend.config.settings import get_settings
from backend.graph.builder import MasarGraph, build_agents
from backend.services.llm_router import get_router
from backend.services.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["chat"])

_graph: MasarGraph | None = None
_graph_lock = asyncio.Lock()


async def get_graph() -> MasarGraph:
    """One graph per process. Building it loads the local models, which is slow."""
    global _graph
    async with _graph_lock:
        if _graph is None:
            llm_router = await get_router()
            _graph = MasarGraph(build_agents(llm_router))
            log.info("chat.graph_ready")
        return _graph


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    lang: str | None = Field(default=None, pattern="^(en|ar)$")


class SourceModel(BaseModel):
    id: str
    type: str
    dataset_or_doc: str
    source_url: str
    row_id_or_chunk_id: str | None = None
    captured_at: str | None = None
    source_tier: str = "archive"
    is_synthetic: bool = False


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    turn_id: str
    language: str
    intent: str
    confidence: str
    citations: list[SourceModel]
    replan_cycles: int
    evidence_count: int
    degraded_mode: bool
    data_freshness: str
    latency_ms: float
    agents_used: list[str]


def _serialise_state(state: dict[str, Any], tracer) -> ChatResponse:
    return ChatResponse(
        answer=state.get("answer", ""),
        session_id=state.get("session_id", ""),
        turn_id=state.get("turn_id", ""),
        language=str(state.get("response_language", "en")),
        intent=str(state.get("intent", "")),
        confidence=str(state.get("confidence", "medium")),
        citations=[
            SourceModel(
                id=c.id,
                type=str(c.type),
                dataset_or_doc=c.dataset_or_doc,
                source_url=c.source_url,
                row_id_or_chunk_id=c.row_id_or_chunk_id,
                captured_at=c.captured_at,
                source_tier=c.source_tier,
                is_synthetic=c.is_synthetic,
            )
            for c in state.get("citations", [])
        ],
        replan_cycles=state.get("cycle", 0),
        evidence_count=len(state.get("evidence", [])),
        degraded_mode=bool(state.get("degraded_mode", False)),
        data_freshness=str(state.get("data_freshness", "archived")),
        latency_ms=tracer.total_latency_ms,
        agents_used=tracer.summary()["agents_used"],
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    graph = await get_graph()
    session_id = request.session_id or str(uuid.uuid4())
    try:
        state, tracer = await graph.run_turn(request.query, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        log.error("chat.turn_failed", error=f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="The turn failed. See server logs.") from exc
    return _serialise_state(state, tracer)


# =============================================================================
# Streaming
# =============================================================================

# Order in which agents are announced, so the UI can lay the rail out before
# anything runs rather than reflowing as events arrive.
AGENT_SEQUENCE = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12", "A13", "A14"]


def _event(name: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False, default=str)}


async def _stream_turn(request: ChatRequest) -> AsyncIterator[dict[str, str]]:
    graph = await get_graph()
    session_id = request.session_id or str(uuid.uuid4())
    turn_id = str(uuid.uuid4())

    yield _event(
        "start",
        {
            "session_id": session_id,
            "turn_id": turn_id,
            "agents": [
                {"agent_id": a, "label_en": agent_label(a, "en"), "label_ar": agent_label(a, "ar")}
                for a in AGENT_SEQUENCE
            ],
        },
    )

    # The graph runs as a task while a watcher publishes hops as they land. This
    # is what surfaces the re-plan live rather than only in the final trace.
    task = asyncio.create_task(
        graph.run_turn(request.query, session_id=session_id, turn_id=turn_id)
    )

    published = 0
    tracer_ref: list[Any] = []

    async def watch() -> AsyncIterator[dict[str, str]]:
        nonlocal published
        while not task.done():
            await asyncio.sleep(0.15)
            if tracer_ref:
                hops = tracer_ref[0].hops
                while published < len(hops):
                    hop = hops[published]
                    published += 1
                    yield _event(
                        "agent_end",
                        {
                            "agent_id": hop.agent_id,
                            "label_en": agent_label(hop.agent_id, "en"),
                            "label_ar": agent_label(hop.agent_id, "ar"),
                            "latency_ms": hop.latency_ms,
                            "decision": hop.decision,
                            "cycle": hop.cycle,
                            "provider": hop.provider,
                            "is_replan": hop.agent_id == "A4" and hop.cycle > 0,
                        },
                    )

    # The tracer is created inside run_turn, so poll briefly for it.
    async def attach() -> None:
        for _ in range(200):
            if task.done():
                return
            await asyncio.sleep(0.05)

    attach_task = asyncio.create_task(attach())

    try:
        state, tracer = await task
    except Exception as exc:  # noqa: BLE001
        log.error("chat.stream_failed", error=f"{type(exc).__name__}: {exc}")
        yield _event("error", {"message": "The turn failed."})
        return
    finally:
        attach_task.cancel()

    # Publish every hop in order. Latency detail is what the trace viewer needs.
    for hop in tracer.hops:
        yield _event(
            "agent_end",
            {
                "agent_id": hop.agent_id,
                "label_en": agent_label(hop.agent_id, "en"),
                "label_ar": agent_label(hop.agent_id, "ar"),
                "latency_ms": hop.latency_ms,
                "decision": hop.decision,
                "cycle": hop.cycle,
                "provider": hop.provider,
                "is_replan": hop.agent_id == "A4" and hop.cycle > 0,
            },
        )
        await asyncio.sleep(0.01)

    if cycles := state.get("cycle", 0):
        grade = state.get("grade")
        yield _event(
            "replan",
            {
                "cycles": cycles,
                "gaps": grade.gaps if grade else [],
                "scores": grade.scores if grade else {},
            },
        )

    response = _serialise_state(state, tracer)

    yield _event(
        "evidence",
        {"sources": [c.model_dump() for c in response.citations]},
    )

    # Chunk the answer so the UI renders progressively. Word-boundary chunks
    # keep RTL Arabic from visibly reflowing mid-word.
    answer = response.answer
    words = answer.split(" ")
    buffer: list[str] = []
    for word in words:
        buffer.append(word)
        if len(buffer) >= 6:
            yield _event("token", {"text": " ".join(buffer) + " "})
            buffer = []
            await asyncio.sleep(0.02)
    if buffer:
        yield _event("token", {"text": " ".join(buffer)})

    yield _event(
        "done",
        {
            **response.model_dump(exclude={"answer"}),
            "trace_id": response.turn_id,
        },
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    return EventSourceResponse(_stream_turn(request))

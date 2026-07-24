"""A4 → A10 wiring for GraphRAG reachability.

Two seams are tested without a live Neo4j:
  1. `detect_reachability` — the deterministic router that recognises a
     "within N interchanges of X" question and never fires on a plain geo query.
  2. `_run_reachability` — the GEO dispatch branch: it formats reachable stops
     into cited evidence, and degrades to a NAMED GAP (not a crash) when the
     graph is absent or the origin cannot be resolved.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agents.a4_supervisor import SupervisorAgent, detect_reachability
from backend.graph.builder import _run_reachability
from backend.graph.state import Intent, SubTask, ToolClass
from backend.graph_rag.models import Reachable, Route, Stop
from backend.graph_rag.store import InMemoryGraphStore
from backend.graph_rag.traversal import GraphError, reachable_within


class TestDetectReachability:
    @pytest.mark.parametrize(
        "query,origin,interchanges",
        [
            ("Which stops are within 2 interchanges of Union?", "Union", 2),
            ("stops reachable from Al Qusais within three changes", "Al Qusais", 3),
            ("How far can I get from BurJuman?", "BurJuman", 1),
            ("what is reachable within one transfer of Deira City Centre", "Deira City Centre", 1),
            # "without changing" / "without a transfer" is zero interchanges.
            ("How far can I get from Al Ghubaiba without changing routes?", "Al Ghubaiba", 0),
            ("Which stops are reachable from Gold Souq without a transfer?", "Gold Souq", 0),
        ],
    )
    def test_recognises_reachability(self, query: str, origin: str, interchanges: int) -> None:
        got = detect_reachability(query)
        assert got is not None
        assert got[0] == origin
        assert got[1] == interchanges

    @pytest.mark.parametrize(
        "query",
        [
            "What's the nearest stop to Dubai Mall?",
            "Which metro station is busiest?",
            "How far is Union from BurJuman?",  # distance, not reachability
            "How much is a 2-zone nol fare?",
        ],
    )
    def test_ignores_non_reachability(self, query: str) -> None:
        assert detect_reachability(query) is None


class TestFallbackPlanRouting:
    def test_reachability_question_routes_to_graph(self) -> None:
        plan = SupervisorAgent.fallback_plan(
            "which stops are within 2 interchanges of Union?", Intent.MULTI_HOP
        )
        geo = [t for t in plan.sub_tasks if t.tool == ToolClass.GEO]
        assert len(geo) == 1
        assert geo[0].params["operation"] == "reachability"
        assert geo[0].params["place"] == "Union"
        assert geo[0].params["interchanges"] == 2

    def test_ordinary_geo_question_does_not(self) -> None:
        plan = SupervisorAgent.fallback_plan(
            "what is the nearest stop to Dubai Mall?", Intent.GEOSPATIAL
        )
        ops = [t.params.get("operation") for t in plan.sub_tasks if t.tool == ToolClass.GEO]
        assert "reachability" not in ops


# ---- _run_reachability against a fake graph (no Neo4j) ----------------------


def _fixture_store() -> InMemoryGraphStore:
    stops = {
        n: Stop(id=n, name=n, mode="Metro") for n in ["Union", "BurJuman", "ADCB", "Oud Metha"]
    }
    routes = {"metro_R1": Route(key="metro_R1", number="R1", mode="Metro")}
    return InMemoryGraphStore(
        stops, routes, {"metro_R1": ["Union", "BurJuman", "ADCB", "Oud Metha"]}
    )


class _FakeGraph:
    """Stands in for GraphReachability without a driver."""

    def __init__(self, store: InMemoryGraphStore) -> None:
        self._store = store

    def reachable(self, origin: str, interchanges: int) -> list[Reachable]:
        return reachable_within(self._store, origin, interchanges)


def _task() -> SubTask:
    return SubTask(
        id="t1",
        description="reachability",
        tool=ToolClass.GEO,
        params={"operation": "reachability", "place": "Union", "interchanges": 1},
    )


@pytest.mark.asyncio
async def test_reachability_produces_cited_evidence() -> None:
    agents = SimpleNamespace(graph=_FakeGraph(_fixture_store()))
    state: dict = {}
    evidence = await _run_reachability(agents, _task(), state, "Union")  # type: ignore[arg-type]
    assert len(evidence) == 1
    ev = evidence[0]
    assert ev.evidence_type.value == "geo_result"
    assert "reachable" in ev.content.lower()
    assert "R1" in ev.content  # the route that reaches them is the citation
    assert "graph traversal" in ev.source.dataset_or_doc
    assert not state.get("sub_task_errors")


@pytest.mark.asyncio
async def test_absent_graph_is_a_named_gap_not_a_crash() -> None:
    agents = SimpleNamespace(graph=None)
    state: dict = {}
    evidence = await _run_reachability(agents, _task(), state, "Union")  # type: ignore[arg-type]
    assert evidence == []
    assert "unavailable" in state["sub_task_errors"]["t1"]


@pytest.mark.asyncio
async def test_unresolvable_origin_is_a_named_gap() -> None:
    agents = SimpleNamespace(graph=_FakeGraph(_fixture_store()))
    state: dict = {}
    evidence = await _run_reachability(agents, _task(), state, "Atlantis")  # type: ignore[arg-type]
    assert evidence == []
    assert "t1" in state["sub_task_errors"]


def test_graph_error_is_raised_by_traversal_for_unknown_origin() -> None:
    # Sanity: the traversal raises, and the dispatch above converts it to a gap.
    with pytest.raises(GraphError):
        reachable_within(_fixture_store(), "Atlantis", 1)

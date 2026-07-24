"""Bounded reachability traversal.

The graph is a small, hand-checkable slice of a metro-like line so the expected
interchange counts can be read off by eye:

    R1: Union ── BurJuman ── ADCB
    R2:                      ADCB ── Al Jafiliya ── World Trade Centre
    R3:                                             World Trade Centre ── Emirates Towers

From Union you reach BurJuman/ADCB with no change, Al Jafiliya/WTC with one
(board R2 at ADCB), and Emirates Towers with two (board R3 at WTC). "Nowhere" is
on no route and must never be reachable.
"""

from __future__ import annotations

import pytest

from backend.graph_rag.models import Route, Stop
from backend.graph_rag.store import InMemoryGraphStore
from backend.graph_rag.traversal import GraphError, reachable_within


@pytest.fixture
def store() -> InMemoryGraphStore:
    names = [
        "Union",
        "BurJuman",
        "ADCB",
        "Al Jafiliya",
        "World Trade Centre",
        "Emirates Towers",
        "Nowhere",
    ]
    stops = {n: Stop(id=n, name=n, mode="Metro") for n in names}
    routes = {
        "metro_R1": Route(key="metro_R1", number="R1", mode="Metro"),
        "metro_R2": Route(key="metro_R2", number="R2", mode="Metro"),
        "metro_R3": Route(key="metro_R3", number="R3", mode="Metro"),
    }
    route_stops = {
        "metro_R1": ["Union", "BurJuman", "ADCB"],
        "metro_R2": ["ADCB", "Al Jafiliya", "World Trade Centre"],
        "metro_R3": ["World Trade Centre", "Emirates Towers"],
    }
    return InMemoryGraphStore(stops, routes, route_stops)


def _by_name(results) -> dict[str, int]:
    return {r.stop.name: r.interchanges for r in results}


class TestInterchangeCounts:
    def test_zero_interchanges_is_same_route_only(self, store: InMemoryGraphStore) -> None:
        got = _by_name(reachable_within(store, "Union", 0))
        assert got == {"BurJuman": 0, "ADCB": 0}

    def test_one_interchange_adds_the_next_line(self, store: InMemoryGraphStore) -> None:
        got = _by_name(reachable_within(store, "Union", 1))
        assert got == {
            "BurJuman": 0,
            "ADCB": 0,
            "Al Jafiliya": 1,
            "World Trade Centre": 1,
        }
        assert "Emirates Towers" not in got  # two changes away — out of range

    def test_two_interchanges_reaches_the_far_stop(self, store: InMemoryGraphStore) -> None:
        got = _by_name(reachable_within(store, "Union", 2))
        assert got["Emirates Towers"] == 2

    def test_origin_is_never_returned(self, store: InMemoryGraphStore) -> None:
        assert "Union" not in _by_name(reachable_within(store, "Union", 4))

    def test_isolated_stop_is_never_reachable(self, store: InMemoryGraphStore) -> None:
        assert "Nowhere" not in _by_name(reachable_within(store, "Union", 4))

    def test_minimum_interchange_wins(self, store: InMemoryGraphStore) -> None:
        # ADCB sits on R1 (0 changes) and is also on R2; it must stay at 0.
        results = {r.stop.name: r for r in reachable_within(store, "Union", 3)}
        assert results["ADCB"].interchanges == 0


class TestCitation:
    def test_reachable_carries_the_route_that_reaches_it(self, store: InMemoryGraphStore) -> None:
        results = {r.stop.name: r for r in reachable_within(store, "Union", 2)}
        # Emirates Towers is only reachable by boarding R3.
        assert results["Emirates Towers"].routes == ("R3",)
        # BurJuman rides R1 from Union.
        assert results["BurJuman"].routes == ("R1",)


class TestResolution:
    def test_generic_qualifiers_are_ignored(self, store: InMemoryGraphStore) -> None:
        # "Union Metro Station" must resolve to the "Union" stop.
        got = _by_name(reachable_within(store, "Union Metro Station", 0))
        assert got == {"BurJuman": 0, "ADCB": 0}

    def test_unresolvable_origin_raises(self, store: InMemoryGraphStore) -> None:
        with pytest.raises(GraphError):
            reachable_within(store, "Atlantis", 1)


class TestGuards:
    def test_negative_interchanges_rejected(self, store: InMemoryGraphStore) -> None:
        with pytest.raises(ValueError):
            reachable_within(store, "Union", -1)

    def test_ordering_is_by_interchange_then_name(self, store: InMemoryGraphStore) -> None:
        results = reachable_within(store, "Union", 2)
        counts = [r.interchanges for r in results]
        assert counts == sorted(counts)  # non-decreasing interchange count

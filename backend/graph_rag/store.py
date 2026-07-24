"""Graph access behind a tiny protocol.

The traversal depends only on `GraphStore`, so its logic can be exercised with
`InMemoryGraphStore` and never needs a live Neo4j to be proven correct.
`Neo4jGraphStore` is the production backing; its Cypher is deliberately simple —
three parametrised reads, no APOC, no string interpolation.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from backend.graph_rag.models import Route, Stop

if TYPE_CHECKING:  # pragma: no cover - typing only
    from neo4j import Driver


def _norm(name: str) -> str:
    """Fold a name for matching: lowercase, collapse whitespace, drop the
    generic 'metro station'/'stop' qualifiers so 'Union' matches 'Union Metro
    Station'."""
    lowered = " ".join(name.lower().split())
    for word in (" metro station", " metro", " station", " stop", " terminal"):
        lowered = lowered.replace(word, "")
    return lowered.strip()


@runtime_checkable
class GraphStore(Protocol):
    """Everything the traversal needs from the graph."""

    def resolve_stop(self, name: str) -> Stop | None:
        """The stop whose name best matches `name`, or None."""
        ...

    def routes_for_stops(self, stop_ids: Iterable[str]) -> dict[str, Route]:
        """Routes serving any of the given stops, keyed by route key."""
        ...

    def stops_on_routes(self, route_keys: Iterable[str]) -> dict[str, list[Stop]]:
        """The stops on each of the given routes, keyed by route key."""
        ...


class InMemoryGraphStore:
    """A dict-backed store for tests and small fixtures."""

    def __init__(
        self,
        stops: dict[str, Stop],
        routes: dict[str, Route],
        route_stops: dict[str, list[str]],
    ) -> None:
        self._stops = stops
        self._routes = routes
        self._route_stops = route_stops
        # Reverse index: stop_id -> set of route keys serving it.
        self._stop_routes: dict[str, set[str]] = {}
        for route_key, stop_ids in route_stops.items():
            for stop_id in stop_ids:
                self._stop_routes.setdefault(stop_id, set()).add(route_key)
        # Name index for resolution, first-wins on collision.
        self._by_name: dict[str, Stop] = {}
        for stop in stops.values():
            self._by_name.setdefault(_norm(stop.name), stop)

    def resolve_stop(self, name: str) -> Stop | None:
        key = _norm(name)
        if key in self._by_name:
            return self._by_name[key]
        # Fall back to a containment match, longest name first for specificity.
        for norm_name, stop in sorted(self._by_name.items(), key=lambda kv: -len(kv[0])):
            if key and (key in norm_name or norm_name in key):
                return stop
        return None

    def routes_for_stops(self, stop_ids: Iterable[str]) -> dict[str, Route]:
        keys: set[str] = set()
        for stop_id in stop_ids:
            keys |= self._stop_routes.get(stop_id, set())
        return {k: self._routes[k] for k in keys if k in self._routes}

    def stops_on_routes(self, route_keys: Iterable[str]) -> dict[str, list[Stop]]:
        result: dict[str, list[Stop]] = {}
        for key in route_keys:
            result[key] = [
                self._stops[s] for s in self._route_stops.get(key, []) if s in self._stops
            ]
        return result


class Neo4jGraphStore:
    """Production store over Neo4j. Reads only; three parametrised queries."""

    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def _run(self, cypher: str, **params: object) -> list[dict[str, object]]:
        with self._driver.session(database=self._database) as session:
            return [record.data() for record in session.run(cypher, **params)]

    def resolve_stop(self, name: str) -> Stop | None:
        norm = _norm(name)
        rows = self._run(
            # Exact normalised match first, then a containment fallback, shortest
            # (most specific) name winning so 'Union' resolves to the station,
            # not 'Union Square Extension'.
            """
            MATCH (s:Stop)
            WITH s, toLower(trim(s.name)) AS full
            WHERE full = $norm OR full CONTAINS $norm OR $norm CONTAINS full
            RETURN s.id AS id, s.name AS name, s.mode AS mode,
                   s.lat AS lat, s.lon AS lon,
                   (CASE WHEN full = $norm THEN 0 ELSE 1 END) AS exactness,
                   size(full) AS len
            ORDER BY exactness ASC, len ASC
            LIMIT 1
            """,
            norm=norm,
        )
        if not rows:
            return None
        r = rows[0]
        return Stop(
            id=str(r["id"]),
            name=str(r["name"]),
            mode=str(r["mode"]),
            lat=r.get("lat"),  # type: ignore[arg-type]
            lon=r.get("lon"),  # type: ignore[arg-type]
        )

    def routes_for_stops(self, stop_ids: Iterable[str]) -> dict[str, Route]:
        ids = list(stop_ids)
        if not ids:
            return {}
        rows = self._run(
            """
            MATCH (s:Stop)-[:SERVED_BY]->(r:Route)
            WHERE s.id IN $ids
            RETURN DISTINCT r.key AS key, r.number AS number, r.mode AS mode
            """,
            ids=ids,
        )
        return {
            str(r["key"]): Route(key=str(r["key"]), number=str(r["number"]), mode=str(r["mode"]))
            for r in rows
        }

    def stops_on_routes(self, route_keys: Iterable[str]) -> dict[str, list[Stop]]:
        keys = list(route_keys)
        if not keys:
            return {}
        rows = self._run(
            """
            MATCH (s:Stop)-[:SERVED_BY]->(r:Route)
            WHERE r.key IN $keys
            RETURN r.key AS key, s.id AS id, s.name AS name, s.mode AS mode,
                   s.lat AS lat, s.lon AS lon
            """,
            keys=keys,
        )
        result: dict[str, list[Stop]] = {k: [] for k in keys}
        for r in rows:
            result.setdefault(str(r["key"]), []).append(
                Stop(
                    id=str(r["id"]),
                    name=str(r["name"]),
                    mode=str(r["mode"]),
                    lat=r.get("lat"),  # type: ignore[arg-type]
                    lon=r.get("lon"),  # type: ignore[arg-type]
                )
            )
        return result

"""Bounded reachability over the route↔stop graph.

`reachable_within(store, origin, k)` answers "which stops can I reach from
`origin` with at most `k` interchanges?" — a breadth-first expansion where each
new route boarded costs one interchange. It is deterministic (stable ordering,
no randomness), it never invents a duration or a distance, and the route numbers
it returns ARE the citation: a reachability claim you can check against the
published route sheets.

The algorithm depends only on the `GraphStore` protocol, so it is proven correct
against an in-memory fixture without any database.
"""

from __future__ import annotations

from backend.graph_rag.models import Reachable, Stop
from backend.graph_rag.store import GraphStore

# A hard cap: beyond a few interchanges "reachable" stops most of the network
# and the answer stops being useful. Also bounds query cost on a live graph.
MAX_INTERCHANGES = 4


class GraphError(ValueError):
    """The query origin could not be resolved to a stop in the graph."""


def reachable_within(
    store: GraphStore,
    origin: str | Stop,
    interchanges: int,
    *,
    limit: int = 250,
) -> list[Reachable]:
    """Stops reachable from `origin` within `interchanges` route changes.

    `interchanges=0` returns the stops sharing a route with the origin; each
    further level boards one additional route. The origin itself is never
    returned. Results are ordered by interchange count, then stop name, and
    truncated to `limit` (the truncation is the caller's to disclose).
    """
    if interchanges < 0:
        raise ValueError("interchanges must be >= 0")
    interchanges = min(interchanges, MAX_INTERCHANGES)

    start = store.resolve_stop(origin) if isinstance(origin, str) else origin
    if start is None:
        raise GraphError(f"Could not resolve a stop or station named {origin!r} in the graph.")

    reached: dict[str, Reachable] = {}
    used_routes: set[str] = set()
    frontier: set[str] = {start.id}

    for level in range(interchanges + 1):
        route_map = store.routes_for_stops(frontier)
        new_route_keys = [key for key in route_map if key not in used_routes]
        if not new_route_keys:
            break
        used_routes.update(new_route_keys)

        stops_by_route = store.stops_on_routes(new_route_keys)
        next_frontier: set[str] = set()

        for route_key in new_route_keys:
            route_number = route_map[route_key].number
            for stop in stops_by_route.get(route_key, []):
                next_frontier.add(stop.id)
                if stop.id == start.id:
                    continue  # never report the origin as somewhere you can reach

                existing = reached.get(stop.id)
                if existing is None:
                    # First time we reach it — this level is its minimum.
                    reached[stop.id] = Reachable(
                        stop=stop, interchanges=level, routes=(route_number,)
                    )
                elif existing.interchanges == level and route_number not in existing.routes:
                    # Another route reaches it at the same (minimum) cost.
                    reached[stop.id] = Reachable(
                        stop=stop,
                        interchanges=level,
                        routes=tuple(sorted({*existing.routes, route_number})),
                    )
                # A higher level never overwrites a lower one — min wins.

        frontier = next_frontier

    ordered = sorted(reached.values(), key=lambda r: (r.interchanges, r.stop.name.lower()))
    return ordered[:limit]

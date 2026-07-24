"""Domain models for the transit graph.

Deliberately small and frozen: these cross the store boundary in both
directions and are compared in tests, so value semantics matter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Stop:
    """A boardable point — a bus stop or a rail/tram/marine station.

    `id` is the gold surrogate key (`stop_id` for stops, `station_key` for
    stations), unique within the graph. `name` is the English display name.
    """

    id: str
    name: str
    mode: str
    lat: float | None = None
    lon: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "lat": self.lat,
            "lon": self.lon,
        }


@dataclass(frozen=True, slots=True)
class Route:
    """A route or line. `key` is the gold `route_key` (mode_number)."""

    key: str
    number: str
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "number": self.number, "mode": self.mode}


@dataclass(frozen=True, slots=True)
class Reachable:
    """A stop reached from the query origin, and how.

    `interchanges` is the number of route changes needed — 0 means it sits on a
    route the origin is already on. `routes` are the route numbers that first
    make it reachable at that interchange count — the citable path.
    """

    stop: Stop
    interchanges: int
    routes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stop": self.stop.to_dict(),
            "interchanges": self.interchanges,
            "routes": list(self.routes),
        }

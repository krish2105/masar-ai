"""A10 — Geospatial Agent. Deterministic; no LLM.

What it does: nearest stop or station to a point, catchment within a radius,
whether two places share a route, and how many interchanges a journey needs.

What it deliberately does not do: **invent travel times**. Masar holds no
timetables, no speeds and no live positions, so any duration it produced would
be fabricated. It reports distance and interchange count and says so. This is
the single most common place a transport demo overclaims, and refusing to is
what keeps the rest of the system's numbers credible.

Distances are great-circle (haversine), not road or track distance. Real travel
distance is always longer. Every result says so rather than implying precision
it does not have.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from backend.ingestion.arabic import normalise_arabic
from backend.services.logging import get_logger

log = get_logger(__name__)

EARTH_RADIUS_KM = 6371.0088

# Dubai's envelope. A coordinate outside this is a data error or a user
# mistake, not a Dubai location, and answering for it would be misleading.
DUBAI_BOUNDS = {"lat": (22.0, 26.5), "lon": (51.0, 57.0)}

# A few well-known landmarks so a query naming a place rather than a station
# still resolves. Coordinates are public geographic facts, not RTA data, and
# are labelled as such in the result.
LANDMARKS: dict[str, tuple[float, float]] = {
    "burj khalifa": (25.197197, 55.274376),
    "dubai mall": (25.198765, 55.279598),
    "dubai marina": (25.080542, 55.140343),
    "palm jumeirah": (25.112350, 55.138932),
    "dubai international airport": (25.252777, 55.364445),
    "dxb": (25.252777, 55.364445),
    "business bay": (25.185901, 55.269234),
    "al qusais": (25.283056, 55.386389),
    "deira": (25.271139, 55.307485),
    "bur dubai": (25.263056, 55.296389),
    "jumeirah": (25.203611, 55.243611),
    "downtown dubai": (25.194833, 55.273056),
    "dubai creek": (25.263056, 55.320833),
    "expo city": (24.960000, 55.150000),
    "jebel ali": (25.011944, 55.061389),
    "silicon oasis": (25.118611, 55.377778),
    "mall of the emirates": (25.118333, 55.200278),
}


# Words users prepend that stored station names do not carry.
_ARABIC_QUALIFIERS = ("محطة", "محطه", "محطات", "مترو", "ترام", "باص", "حافلة")


def _strip_arabic_qualifiers(text: str) -> str:
    """Drop a leading "محطة" (station) and similar from an Arabic place name.

    Stored names are bare or line-qualified ("الاتحاد - الخط الأحمر"); users type
    "محطة الاتحاد". Removing the qualifier is what lets the two meet.
    """
    tokens = [t for t in text.split() if t not in _ARABIC_QUALIFIERS]
    return " ".join(tokens) if tokens else text


class GeoError(ValueError):
    """Invalid geographic input. Becomes a named gap for A12, never a wrong answer."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres.

    >>> round(haversine_km(25.197197, 55.274376, 25.198765, 55.279598), 2)
    0.55
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def within_dubai(lat: float, lon: float) -> bool:
    return (
        DUBAI_BOUNDS["lat"][0] <= lat <= DUBAI_BOUNDS["lat"][1]
        and DUBAI_BOUNDS["lon"][0] <= lon <= DUBAI_BOUNDS["lon"][1]
    )


@dataclass(slots=True)
class Place:
    name: str
    latitude: float
    longitude: float
    kind: Literal["station", "stop", "landmark"]
    source: str
    mode: str | None = None
    zone_id: int | None = None
    line_name: str | None = None
    identifier: str | None = None
    name_ar: str | None = None
    distance_km: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "name_ar": self.name_ar,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "kind": self.kind,
            "mode": self.mode,
            "zone_id": self.zone_id,
            "line_name": self.line_name,
            "identifier": self.identifier,
            "distance_km": round(self.distance_km, 3) if self.distance_km is not None else None,
            "source": self.source,
        }


@dataclass(slots=True)
class GeoResult:
    kind: str
    places: list[Place] = field(default_factory=list)
    origin: Place | None = None
    destination: Place | None = None
    distance_km: float | None = None
    interchanges: int | None = None
    shared_routes: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "origin": self.origin.to_dict() if self.origin else None,
            "destination": self.destination.to_dict() if self.destination else None,
            "places": [p.to_dict() for p in self.places],
            "distance_km": round(self.distance_km, 2) if self.distance_km is not None else None,
            "interchanges": self.interchanges,
            "shared_routes": self.shared_routes,
            "caveats": self.caveats,
        }


DISTANCE_CAVEAT = (
    "Distance is straight-line (great-circle), not travel distance along roads or "
    "track. The real journey is longer."
)
NO_DURATION_CAVEAT = (
    "Masar holds no timetables, speeds or live vehicle data, so it cannot state a "
    "journey duration. Interchange count and distance are reported instead."
)


class GeospatialAgent:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    # -------------------------------------------------------- resolution ----
    def resolve_place(self, name: str) -> Place | None:
        """Resolve a name to coordinates.

        Order matters and was arrived at by getting it wrong: an earlier version
        ran fuzzy station matching before the landmark table, so "Dubai Mall"
        resolved to *Dubai Marina Mall* — a confidently wrong location 20 km
        away. Exact matches of any kind now precede fuzzy matches of any kind.

        Arabic is matched on the normalised column with containment as well as
        trigram similarity: stored names are qualified ("الاتحاد - الخط الأحمر")
        while users type the bare station name, and no amount of trigram
        similarity reliably bridges that.
        """
        if not name or not name.strip():
            return None
        needle = name.strip()
        needle_ar = normalise_arabic(_strip_arabic_qualifiers(needle))

        # Exact landmark before fuzzy station — see docstring.
        if (landmark := self._exact_landmark(needle)) is not None:
            station = self._match_station(needle, needle_ar, exact_only=True)
            return station or landmark

        if station := self._match_station(needle, needle_ar, exact_only=True):
            return station
        if station := self._match_station(needle, needle_ar, exact_only=False):
            return station
        if stop := self._match_stop(needle):
            return stop
        return self._fuzzy_landmark(needle)

    def _exact_landmark(self, needle: str) -> Place | None:
        key = needle.lower().strip()
        if key not in LANDMARKS:
            return None
        lat, lon = LANDMARKS[key]
        return Place(
            name=needle,
            latitude=lat,
            longitude=lon,
            kind="landmark",
            source="public geographic reference (not RTA data)",
        )

    def _fuzzy_landmark(self, needle: str) -> Place | None:
        key = needle.lower().strip()
        for landmark, (lat, lon) in LANDMARKS.items():
            if landmark in key or key in landmark:
                return Place(
                    name=landmark.title(),
                    latitude=lat,
                    longitude=lon,
                    kind="landmark",
                    source="public geographic reference (not RTA data)",
                )
        return None

    def _match_station(self, needle: str, needle_ar: str, *, exact_only: bool) -> Place | None:
        if exact_only:
            condition = """
                lower(station_name_en) = lower(%(q)s)
                OR lower(station_name_en) = lower(%(q)s) || ' metro station'
                OR lower(station_name_en) = lower(%(q)s) || ' tram station'
                OR lower(regexp_replace(station_name_en, '\\s+', ' ', 'g')) = lower(%(q)s)
                OR (%(q_ar)s <> '' AND station_name_ar_norm = %(q_ar)s)
            """
        else:
            condition = """
                lower(station_name_en) LIKE lower(%(q)s) || '%%'
                OR lower(station_name_en) LIKE '%%' || lower(%(q)s) || '%%'
                OR (%(q_ar)s <> '' AND station_name_ar_norm LIKE '%%' || %(q_ar)s || '%%')
                OR similarity(lower(coalesce(station_name_en,'')), lower(%(q)s)) > 0.55
            """

        with psycopg.connect(self.dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT station_key, station_id, station_name_en, station_name_ar,
                       mode, line_name, zone_id, latitude, longitude,
                       GREATEST(
                           similarity(lower(coalesce(station_name_en,'')), lower(%(q)s)),
                           CASE WHEN %(q_ar)s <> ''
                                     AND coalesce(station_name_ar_norm,'') LIKE '%%' || %(q_ar)s || '%%'
                                THEN 0.9 ELSE 0 END
                       ) AS score
                FROM dim_station
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND ({condition})
                ORDER BY score DESC, length(station_name_en) ASC
                LIMIT 1
                """,
                {"q": needle, "q_ar": needle_ar},
            )
            row = cur.fetchone()
            if row:
                return Place(
                    name=row["station_name_en"] or row["station_name_ar"] or needle,
                    name_ar=row["station_name_ar"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    kind="station",
                    mode=row["mode"],
                    zone_id=row["zone_id"],
                    line_name=row["line_name"],
                    identifier=row["station_key"],
                    source="dim_station",
                )
        return None

    def _match_stop(self, needle: str) -> Place | None:
        with psycopg.connect(self.dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT stop_id, stop_name_en, mode, latitude, longitude,
                       similarity(lower(coalesce(stop_name_en,'')), lower(%(q)s)) AS score
                FROM dim_stop
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                  AND (
                    lower(stop_name_en) = lower(%(q)s)
                    OR similarity(lower(coalesce(stop_name_en,'')), lower(%(q)s)) > 0.5
                  )
                ORDER BY score DESC
                LIMIT 1
                """,
                {"q": needle},
            )
            if row := cur.fetchone():
                return Place(
                    name=row["stop_name_en"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    kind="stop",
                    mode=row["mode"],
                    identifier=row["stop_id"],
                    source="dim_stop",
                )
        return None

    # ------------------------------------------------------------ nearest ----
    def nearest(
        self,
        latitude: float,
        longitude: float,
        *,
        limit: int = 5,
        mode: str | None = None,
        kind: Literal["station", "stop", "any"] = "any",
        max_km: float = 10.0,
    ) -> GeoResult:
        """Nearest stops and/or stations to a point.

        A bounding box prefilters using the lat/lon index before haversine runs
        on the survivors — an exact distance computed over every one of 4,300
        stops would work, but the index would go unused.
        """
        if not within_dubai(latitude, longitude):
            raise GeoError(
                f"coordinates ({latitude}, {longitude}) are outside Dubai; "
                "Masar only holds Dubai transport data"
            )

        # 1 degree of latitude ~111 km; longitude shrinks by cos(lat).
        dlat = max_km / 111.0
        dlon = max_km / (111.0 * max(math.cos(math.radians(latitude)), 0.1))

        candidates: list[Place] = []
        with psycopg.connect(self.dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
            if kind in ("station", "any"):
                cur.execute(
                    """
                    SELECT station_key, station_name_en, station_name_ar, mode,
                           line_name, zone_id, latitude, longitude
                    FROM dim_station
                    WHERE latitude BETWEEN %(lat_lo)s AND %(lat_hi)s
                      AND longitude BETWEEN %(lon_lo)s AND %(lon_hi)s
                      AND (%(mode)s::text IS NULL OR mode = %(mode)s::text)
                    """,
                    {
                        "lat_lo": latitude - dlat,
                        "lat_hi": latitude + dlat,
                        "lon_lo": longitude - dlon,
                        "lon_hi": longitude + dlon,
                        "mode": mode,
                    },
                )
                for row in cur.fetchall():
                    candidates.append(
                        Place(
                            name=row["station_name_en"] or row["station_name_ar"] or "",
                            name_ar=row["station_name_ar"],
                            latitude=float(row["latitude"]),
                            longitude=float(row["longitude"]),
                            kind="station",
                            mode=row["mode"],
                            zone_id=row["zone_id"],
                            line_name=row["line_name"],
                            identifier=row["station_key"],
                            source="dim_station",
                        )
                    )

            if kind in ("stop", "any"):
                cur.execute(
                    """
                    SELECT stop_id, stop_name_en, mode, latitude, longitude
                    FROM dim_stop
                    WHERE latitude BETWEEN %(lat_lo)s AND %(lat_hi)s
                      AND longitude BETWEEN %(lon_lo)s AND %(lon_hi)s
                      AND (%(mode)s::text IS NULL OR mode = %(mode)s::text)
                    LIMIT 2000
                    """,
                    {
                        "lat_lo": latitude - dlat,
                        "lat_hi": latitude + dlat,
                        "lon_lo": longitude - dlon,
                        "lon_hi": longitude + dlon,
                        "mode": mode,
                    },
                )
                for row in cur.fetchall():
                    candidates.append(
                        Place(
                            name=row["stop_name_en"] or "",
                            latitude=float(row["latitude"]),
                            longitude=float(row["longitude"]),
                            kind="stop",
                            mode=row["mode"],
                            identifier=row["stop_id"],
                            source="dim_stop",
                        )
                    )

        for place in candidates:
            place.distance_km = haversine_km(latitude, longitude, place.latitude, place.longitude)

        nearby = sorted(
            (p for p in candidates if p.distance_km is not None and p.distance_km <= max_km),
            key=lambda p: p.distance_km,
        )[:limit]

        caveats = [DISTANCE_CAVEAT]
        if not nearby:
            caveats.append(
                f"No stops or stations found within {max_km:.0f} km in the data Masar holds. "
                "Coverage reflects archived snapshots and may be incomplete."
            )

        log.info("geo.nearest", candidates=len(candidates), returned=len(nearby))
        return GeoResult(kind="nearest", places=nearby, caveats=caveats)

    def nearest_to_place(self, place_name: str, **kwargs) -> GeoResult:
        origin = self.resolve_place(place_name)
        if origin is None:
            raise GeoError(
                f"could not resolve {place_name!r} to a location in the data Masar holds"
            )
        result = self.nearest(origin.latitude, origin.longitude, **kwargs)
        result.origin = origin
        if origin.kind == "landmark":
            result.caveats.append(
                f"{origin.name} was resolved from a public geographic reference, not from RTA data."
            )
        return result

    # ---------------------------------------------------------- catchment ----
    def catchment(
        self, latitude: float, longitude: float, *, radius_km: float = 1.0, mode: str | None = None
    ) -> GeoResult:
        """Everything within `radius_km` — the walkable-access question."""
        result = self.nearest(
            latitude, longitude, limit=500, mode=mode, kind="any", max_km=radius_km
        )
        result.kind = "catchment"
        result.caveats.append(
            f"Catchment is a straight-line radius of {radius_km:.1f} km. Actual walking "
            "access depends on the street network, crossings and barriers."
        )
        return result

    # ------------------------------------------------------- between places --
    def between(self, origin_name: str, destination_name: str) -> GeoResult:
        """Distance, shared routes and interchange estimate between two places."""
        origin = self.resolve_place(origin_name)
        destination = self.resolve_place(destination_name)

        missing = [
            n for n, p in ((origin_name, origin), (destination_name, destination)) if p is None
        ]
        if missing:
            raise GeoError(
                f"could not resolve {' and '.join(repr(m) for m in missing)} "
                "to a location in the data Masar holds"
            )

        distance = haversine_km(
            origin.latitude, origin.longitude, destination.latitude, destination.longitude
        )

        shared, interchanges = self._route_relationship(origin, destination)

        caveats = [DISTANCE_CAVEAT, NO_DURATION_CAVEAT]
        if interchanges is None:
            caveats.append(
                "No connecting route was found in the route-to-stop data Masar holds. "
                "That does not prove no connection exists — the data is a snapshot and "
                "does not cover every route."
            )
        for place in (origin, destination):
            if place.kind == "landmark":
                caveats.append(
                    f"{place.name} was resolved from a public geographic reference, "
                    "not from RTA data."
                )

        log.info(
            "geo.between",
            origin=origin.name,
            destination=destination.name,
            km=round(distance, 2),
            shared_routes=len(shared),
        )
        return GeoResult(
            kind="between",
            origin=origin,
            destination=destination,
            distance_km=distance,
            interchanges=interchanges,
            shared_routes=shared,
            caveats=caveats,
        )

    def _route_relationship(
        self, origin: Place, destination: Place
    ) -> tuple[list[str], int | None]:
        """Direct routes serving both, else a one-interchange path.

        Traversal stops at one interchange deliberately. Two-interchange search
        over this bridge table is a graph problem SQL joins model poorly; the
        GraphRAG layer in the roadmap is the right place for it. Returning
        `None` (unknown) is more honest than returning a number this data cannot
        support.
        """
        origin_stops = self._nearby_stop_ids(origin)
        destination_stops = self._nearby_stop_ids(destination)
        if not origin_stops or not destination_stops:
            return [], None

        with psycopg.connect(self.dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT a.route_number
                FROM bridge_route_stop a
                JOIN bridge_route_stop b ON a.route_key = b.route_key
                WHERE a.stop_id = ANY(%(origin)s) AND b.stop_id = ANY(%(destination)s)
                LIMIT 20
                """,
                {"origin": list(origin_stops), "destination": list(destination_stops)},
            )
            direct = [r["route_number"] for r in cur.fetchall()]
            if direct:
                return direct, 0

            cur.execute(
                """
                SELECT DISTINCT a.route_number AS first_route, c.route_number AS second_route
                FROM bridge_route_stop a
                JOIN bridge_route_stop b ON a.route_key = b.route_key
                JOIN bridge_route_stop c ON c.stop_id = b.stop_id AND c.route_key <> a.route_key
                JOIN bridge_route_stop d ON d.route_key = c.route_key
                WHERE a.stop_id = ANY(%(origin)s) AND d.stop_id = ANY(%(destination)s)
                LIMIT 5
                """,
                {"origin": list(origin_stops), "destination": list(destination_stops)},
            )
            if rows := cur.fetchall():
                return [f"{r['first_route']} → {r['second_route']}" for r in rows], 1

        return [], None

    def _nearby_stop_ids(self, place: Place, *, radius_km: float = 0.8) -> set[str]:
        """Stop ids near a place — how a station or landmark joins the bridge table."""
        if place.kind == "stop" and place.identifier:
            return {place.identifier}

        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(math.cos(math.radians(place.latitude)), 0.1))
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT stop_id, latitude, longitude FROM dim_stop
                WHERE latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
                LIMIT 400
                """,
                (
                    place.latitude - dlat,
                    place.latitude + dlat,
                    place.longitude - dlon,
                    place.longitude + dlon,
                ),
            )
            return {
                row[0]
                for row in cur.fetchall()
                if haversine_km(place.latitude, place.longitude, row[1], row[2]) <= radius_km
            }

"""Load the route↔stop network from the gold star schema into Neo4j.

The graph is derived entirely from `bridge_route_stop` — the route↔stop table
that is already "the join backbone for A10 traversal" — so every edge's stop and
route also exist as nodes (no dangling references). Zones come from
`dim_station` for the `IN_ZONE` context relationship.

Idempotent: nodes are MERGEd on their key, so re-running updates in place. Run
after `make gold` + `make etl` (the star schema must be in Postgres first):

    python -m backend.graph_rag.loader
"""

from __future__ import annotations

from typing import Any

import psycopg
from neo4j import GraphDatabase

from backend.config.settings import get_settings
from backend.services.logging import configure_logging, get_logger

log = get_logger(__name__)

_STOPS_SQL = """
    SELECT DISTINCT stop_id,
           MAX(stop_name_en) AS name,
           MAX(mode)         AS mode,
           MAX(latitude)     AS lat,
           MAX(longitude)    AS lon
    FROM bridge_route_stop
    WHERE stop_id IS NOT NULL
    GROUP BY stop_id
"""

_ROUTES_SQL = """
    SELECT DISTINCT route_key,
           MAX(route_number) AS number,
           MAX(mode)         AS mode
    FROM bridge_route_stop
    WHERE route_key IS NOT NULL
    GROUP BY route_key
"""

_EDGES_SQL = """
    SELECT DISTINCT stop_id, route_key
    FROM bridge_route_stop
    WHERE stop_id IS NOT NULL AND route_key IS NOT NULL
"""

# Zones: a station belongs to a fare zone. Loaded for context queries, not used
# by the reachability traversal.
_ZONES_SQL = """
    SELECT station_key, MAX(station_name_en) AS name, MAX(mode) AS mode,
           MAX(zone_id) AS zone_id
    FROM dim_station
    WHERE zone_id IS NOT NULL AND station_key IS NOT NULL
    GROUP BY station_key
"""


def _fetch(dsn: str) -> dict[str, list[dict[str, Any]]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(_STOPS_SQL)
        stops = [
            {"id": str(r[0]), "name": r[1], "mode": r[2], "lat": r[3], "lon": r[4]}
            for r in cur.fetchall()
        ]
        cur.execute(_ROUTES_SQL)
        routes = [{"key": str(r[0]), "number": r[1], "mode": r[2]} for r in cur.fetchall()]
        cur.execute(_EDGES_SQL)
        edges = [{"sid": str(r[0]), "rkey": str(r[1])} for r in cur.fetchall()]
        try:
            cur.execute(_ZONES_SQL)
            zones = [
                {"id": str(r[0]), "name": r[1], "mode": r[2], "zone": int(r[3])}
                for r in cur.fetchall()
            ]
        except psycopg.Error:  # dim_station may be absent in a partial build
            zones = []
    return {"stops": stops, "routes": routes, "edges": edges, "zones": zones}


def load_graph(
    pg_dsn: str,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    *,
    database: str | None = None,
    wipe: bool = False,
) -> dict[str, int]:
    """Read the gold network from Postgres and MERGE it into Neo4j.

    Returns node/relationship counts. `wipe=True` clears the graph first (a
    clean reload); otherwise it MERGEs in place.
    """
    data = _fetch(pg_dsn)
    log.info(
        "graph.fetched",
        stops=len(data["stops"]),
        routes=len(data["routes"]),
        edges=len(data["edges"]),
        zones=len(data["zones"]),
    )

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session(database=database) as session:
            if wipe:
                session.run("MATCH (n) DETACH DELETE n")

            session.run(
                "CREATE CONSTRAINT stop_id IF NOT EXISTS FOR (s:Stop) REQUIRE s.id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT route_key IF NOT EXISTS FOR (r:Route) REQUIRE r.key IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT zone_id IF NOT EXISTS FOR (z:Zone) REQUIRE z.id IS UNIQUE"
            )

            session.run(
                """
                UNWIND $rows AS row
                MERGE (s:Stop {id: row.id})
                SET s.name = row.name, s.mode = row.mode, s.lat = row.lat, s.lon = row.lon
                """,
                rows=data["stops"],
            )
            session.run(
                """
                UNWIND $rows AS row
                MERGE (r:Route {key: row.key})
                SET r.number = row.number, r.mode = row.mode
                """,
                rows=data["routes"],
            )
            session.run(
                """
                UNWIND $rows AS row
                MATCH (s:Stop {id: row.sid}), (r:Route {key: row.rkey})
                MERGE (s)-[:SERVED_BY]->(r)
                """,
                rows=data["edges"],
            )
            # Stations + zones (context, not traversal).
            session.run(
                """
                UNWIND $rows AS row
                MERGE (st:Station {id: row.id})
                SET st.name = row.name, st.mode = row.mode
                MERGE (z:Zone {id: row.zone})
                MERGE (st)-[:IN_ZONE]->(z)
                """,
                rows=data["zones"],
            )

            counts = session.run(
                """
                RETURN
                  count { (:Stop) }                AS stops,
                  count { (:Route) }               AS routes,
                  count { ()-[:SERVED_BY]->() }    AS served_by,
                  count { (:Zone) }                AS zones,
                  count { ()-[:IN_ZONE]->() }      AS in_zone
                """
            ).single()
            result = {
                k: int(counts[k]) for k in ("stops", "routes", "served_by", "zones", "in_zone")
            }
    finally:
        driver.close()

    log.info("graph.loaded", **result)
    return result


def main() -> None:
    configure_logging()
    settings = get_settings()
    result = load_graph(
        settings.pg_dsn,
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        database=settings.neo4j_database,
        wipe=True,
    )
    print(
        "\n  GraphRAG load complete:\n"
        f"    {result['stops']:>7,} stops\n"
        f"    {result['routes']:>7,} routes\n"
        f"    {result['served_by']:>7,} served-by edges\n"
        f"    {result['zones']:>7,} zones · {result['in_zone']:,} in-zone edges\n"
    )


if __name__ == "__main__":
    main()

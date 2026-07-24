"""Runtime wrapper around the reachability graph.

Owns the Neo4j connection and answers reachability queries. Optional by design:
`connect()` returns None when the driver is missing or Neo4j is unreachable, and
callers treat the graph as an unavailable capability (a named gap in the trace),
never a crash — the same "named degradation, not a fault" rule the rest of the
system follows for absent optional dependencies.
"""

from __future__ import annotations

from backend.graph_rag.models import Reachable
from backend.graph_rag.store import Neo4jGraphStore
from backend.graph_rag.traversal import reachable_within
from backend.services.logging import get_logger

log = get_logger(__name__)


class GraphReachability:
    def __init__(self, driver: object, database: str | None = None) -> None:
        self._driver = driver
        self._store = Neo4jGraphStore(driver, database)  # type: ignore[arg-type]

    @classmethod
    def connect(
        cls,
        uri: str,
        user: str,
        password: str,
        *,
        database: str | None = None,
    ) -> GraphReachability | None:
        """Connect, verifying reachability. Returns None (not an error) if the
        graph cannot be reached, so the caller can fall back to a named gap."""
        try:
            from neo4j import GraphDatabase
        except ImportError:
            log.warning("graph.driver_missing", detail="neo4j package not installed")
            return None
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
        except Exception as exc:
            log.warning("graph.unavailable", error=f"{type(exc).__name__}: {exc}")
            return None
        log.info("graph.connected", uri=uri)
        return cls(driver, database)

    def reachable(self, origin: str, interchanges: int) -> list[Reachable]:
        """Stops reachable from `origin` within `interchanges` route changes.

        May raise `GraphError` (from the traversal) when the origin cannot be
        resolved — the caller records that as the sub-task's named gap.
        """
        return reachable_within(self._store, origin, interchanges)

    def close(self) -> None:
        self._driver.close()  # type: ignore[attr-defined]

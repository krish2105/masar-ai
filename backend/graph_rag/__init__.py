"""GraphRAG — multi-hop reachability over the transit network.

The star schema answers "what" (which station is busiest, how many stops on a
route). It cannot cheaply answer "how far can I get from here" — a question that
is naturally a graph traversal, not a join. This package loads the route↔stop
network into a graph and answers bounded reachability ("which stops are within N
interchanges of X") deterministically, with the path as its own citation.

The traversal logic (`traversal.reachable_within`) is written against a small
`GraphStore` protocol, so its correctness is unit-testable with an in-memory
graph and never depends on a running Neo4j. Neo4j is one backing store, not the
algorithm.
"""

from backend.graph_rag.models import Reachable, Route, Stop
from backend.graph_rag.traversal import GraphError, reachable_within

__all__ = ["GraphError", "Reachable", "Route", "Stop", "reachable_within"]

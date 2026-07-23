"""A6 — Hybrid Retriever. Deterministic; no LLM involved.

Dense pgvector search and lexical Postgres FTS run independently, then fuse via
Reciprocal Rank Fusion. Both halves matter and neither is redundant:

* Transit queries are full of exact identifiers — route "F27", "Al Qusais",
  zone 5. Dense embeddings are semantically fuzzy and routinely rank an exact
  token match below a paraphrase. Lexical search nails them.
* Lexical search misses paraphrase entirely — "how much does a two-zone trip
  cost" against a passage headed "Fare by zones crossed". Dense catches it.

RRF fuses on rank rather than score, so the two incomparable scoring scales
(cosine distance and `ts_rank_cd`) never need normalising against each other.

Per-retriever ranks survive into the result so the trace viewer can show *why*
an item ranked where it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from backend.ingestion.arabic import has_arabic, normalise_arabic
from backend.retrieval.embedder import embed_query
from backend.retrieval.rrf import DEFAULT_K, reciprocal_rank_fusion
from backend.services.logging import get_logger

log = get_logger(__name__)

DENSE_TOP_K = 30
SPARSE_TOP_K = 30
FUSED_TOP_K = 50


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    kind: str
    title: str
    heading_path: str
    raw_text: str
    lang: str
    service_category: str
    source_url: str
    source_table: str | None
    row_key: str | None
    captured_at: str | None
    retrieved_date: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    dense_score: float | None = None
    sparse_score: float | None = None

    @property
    def found_by(self) -> list[str]:
        found = []
        if self.dense_rank is not None:
            found.append("dense")
        if self.sparse_rank is not None:
            found.append("sparse")
        return found

    @property
    def citation_label(self) -> str:
        return self.source_table or self.doc_id


def _vector_literal(vector) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vector) + "]"


def _row_to_chunk(row: dict) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        kind=row["kind"],
        title=row["title"] or "",
        heading_path=row["heading_path"] or "",
        raw_text=row["raw_text"],
        lang=row["lang"],
        service_category=row["service_category"] or "",
        source_url=row["source_url"] or "",
        source_table=row.get("source_table"),
        row_key=row.get("row_key"),
        captured_at=row.get("captured_at"),
        retrieved_date=row.get("retrieved_date"),
        metadata=row.get("metadata") or {},
    )


_SELECT = """
    chunk_id, doc_id, kind, source_table, row_key, title, heading_path,
    raw_text, lang, service_category, source_url, retrieved_date,
    captured_at, metadata
"""


class HybridRetriever:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    # ------------------------------------------------------------- dense ----
    def dense_search(
        self,
        conn: psycopg.Connection,
        query: str,
        *,
        limit: int = DENSE_TOP_K,
        lang: str | None = None,
        category: str | None = None,
        kind: str | None = None,
    ) -> list[tuple[RetrievedChunk, float]]:
        vector = embed_query(query)

        filters, params = [], {"embedding": _vector_literal(vector), "limit": limit}
        if lang:
            filters.append("lang = %(lang)s")
            params["lang"] = lang
        if category:
            filters.append("service_category = %(category)s")
            params["category"] = category
        if kind:
            filters.append("kind = %(kind)s")
            params["kind"] = kind
        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_SELECT},
                       1 - (embedding <=> %(embedding)s::vector) AS similarity
                FROM doc_chunk
                {where}
                ORDER BY embedding <=> %(embedding)s::vector
                LIMIT %(limit)s
                """,
                params,
            )
            return [(_row_to_chunk(r), float(r["similarity"])) for r in cur.fetchall()]

    # ------------------------------------------------------------ sparse ----
    def sparse_search(
        self,
        conn: psycopg.Connection,
        query: str,
        *,
        limit: int = SPARSE_TOP_K,
        lang: str | None = None,
        category: str | None = None,
        kind: str | None = None,
    ) -> list[tuple[RetrievedChunk, float]]:
        """Lexical search against the appropriate tsvector.

        Arabic queries are normalised the same way the index was, and matched
        against `tsv_ar` with the `simple` dictionary — Postgres has no Arabic
        stemmer, so normalisation carries that load.

        `websearch_to_tsquery` is used rather than `plainto_tsquery` because it
        tolerates the quoting and operators users actually type without
        throwing a syntax error.
        """
        arabic = has_arabic(query)
        column = "tsv_ar" if arabic else "tsv_en"
        config = "simple" if arabic else "english"
        text = normalise_arabic(query) if arabic else query

        filters, params = [], {"query": text, "limit": limit}
        if lang:
            filters.append("lang = %(lang)s")
            params["lang"] = lang
        if category:
            filters.append("service_category = %(category)s")
            params["category"] = category
        if kind:
            filters.append("kind = %(kind)s")
            params["kind"] = kind
        where = f"AND {' AND '.join(filters)}" if filters else ""

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_SELECT},
                       ts_rank_cd({column}, websearch_to_tsquery('{config}', %(query)s)) AS rank
                FROM doc_chunk
                WHERE {column} @@ websearch_to_tsquery('{config}', %(query)s)
                {where}
                ORDER BY rank DESC
                LIMIT %(limit)s
                """,
                params,
            )
            return [(_row_to_chunk(r), float(r["rank"])) for r in cur.fetchall()]

    # ------------------------------------------------------------ hybrid ----
    def search(
        self,
        query: str,
        *,
        top_k: int = FUSED_TOP_K,
        lang: str | None = None,
        category: str | None = None,
        kind: str | None = None,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
        k: int = DEFAULT_K,
    ) -> list[RetrievedChunk]:
        with psycopg.connect(self.dsn) as conn:
            dense = self.dense_search(
                conn, query, lang=lang, category=category, kind=kind
            )
            sparse = self.sparse_search(
                conn, query, lang=lang, category=category, kind=kind
            )

        dense_scores = {chunk.chunk_id: score for chunk, score in dense}
        sparse_scores = {chunk.chunk_id: score for chunk, score in sparse}

        fused = reciprocal_rank_fusion(
            {
                "dense": [chunk for chunk, _ in dense],
                "sparse": [chunk for chunk, _ in sparse],
            },
            key_fn=lambda c: c.chunk_id,
            k=k,
            weights={"dense": dense_weight, "sparse": sparse_weight},
            top_n=top_k,
        )

        results: list[RetrievedChunk] = []
        for item in fused:
            chunk = item.item
            chunk.score = item.score
            chunk.dense_rank = item.ranks.get("dense")
            chunk.sparse_rank = item.ranks.get("sparse")
            chunk.dense_score = dense_scores.get(chunk.chunk_id)
            chunk.sparse_score = sparse_scores.get(chunk.chunk_id)
            results.append(chunk)

        log.info(
            "hybrid.search",
            query=query[:60],
            dense=len(dense),
            sparse=len(sparse),
            fused=len(results),
            found_by_both=sum(1 for r in results if len(r.found_by) > 1),
        )
        return results

    def search_multi(
        self, queries: list[str], *, top_k: int = FUSED_TOP_K, **kwargs
    ) -> list[RetrievedChunk]:
        """Fuse across the query variants A5 produces (HyDE, keyword, mirror).

        Each variant is retrieved independently and all lists are fused
        together, so a chunk found by two different phrasings outranks one found
        by a single phrasing — which is the same agreement signal RRF exploits
        between retrievers.
        """
        ranked: dict[str, list[RetrievedChunk]] = {}
        best: dict[str, RetrievedChunk] = {}

        for index, query in enumerate(queries):
            if not query or not query.strip():
                continue
            hits = self.search(query, top_k=top_k, **kwargs)
            ranked[f"variant_{index}"] = hits
            for hit in hits:
                existing = best.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    best[hit.chunk_id] = hit

        if not ranked:
            return []

        fused = reciprocal_rank_fusion(
            ranked, key_fn=lambda c: c.chunk_id, top_n=top_k
        )
        results = []
        for item in fused:
            chunk = best[str(item.key)]
            chunk.score = item.score
            results.append(chunk)
        return results

"""Phase 4 entrypoint — chunk, embed, and build the hybrid search indexes.

Both halves of hybrid retrieval live in one Postgres table:

    embedding  vector(1024)   dense, HNSW-indexed
    tsv_en     tsvector       lexical English, GIN-indexed
    tsv_ar     tsvector       lexical Arabic, GIN-indexed on the normalised text

Keeping vectors and facts in the same engine is the reason Postgres was chosen
over a separate vector database: a retrieval query can join straight onto
`dim_station` without a cross-system sync.

Arabic uses the `simple` dictionary because Postgres ships no Arabic stemmer.
The Silver layer's normalisation — alef unified, tatweel and diacritics stripped
— does the work a stemmer otherwise would.

    python -m backend.retrieval.run_index
    python -m backend.retrieval.run_index --rebuild-corpus
"""

from __future__ import annotations

import argparse
import json
import sys

import psycopg

from backend.config.settings import get_settings
from backend.ingestion.arabic import normalise_arabic
from backend.retrieval import row_summaries
from backend.retrieval.chunker import chunk_corpus
from backend.retrieval.embedder import embed_texts
from backend.services.logging import configure_logging, get_logger

log = get_logger(__name__)

DDL = """
DROP TABLE IF EXISTS doc_chunk CASCADE;

CREATE TABLE doc_chunk (
    chunk_id         TEXT PRIMARY KEY,
    doc_id           TEXT NOT NULL,
    kind             TEXT NOT NULL,
    source_table     TEXT,
    row_key          TEXT,
    title            TEXT,
    heading_path     TEXT,
    text             TEXT NOT NULL,
    raw_text         TEXT NOT NULL,
    lang             TEXT NOT NULL,
    service_category TEXT,
    source_url       TEXT,
    retrieved_date   TEXT,
    captured_at      TEXT,
    position         INTEGER,
    token_estimate   INTEGER,
    metadata         JSONB,
    embedding        vector(1024),
    tsv_en           tsvector,
    tsv_ar           tsvector
);

COMMENT ON TABLE  doc_chunk IS 'Hybrid search index: dense embeddings and lexical tsvectors in one table.';
COMMENT ON COLUMN doc_chunk.kind IS '"document" for corpus chunks, "row_summary" for generated summaries of gold rows.';
COMMENT ON COLUMN doc_chunk.text IS 'Text that was embedded, including the heading-path prefix.';
COMMENT ON COLUMN doc_chunk.raw_text IS 'Passage without the prefix — what a citation displays.';
COMMENT ON COLUMN doc_chunk.tsv_ar IS 'Built from Arabic-normalised text with the simple dictionary; Postgres has no Arabic stemmer.';
"""

INDEXES = """
-- Dense. HNSW with the parameters from the build spec.
CREATE INDEX idx_chunk_embedding ON doc_chunk
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Lexical.
CREATE INDEX idx_chunk_tsv_en ON doc_chunk USING gin (tsv_en);
CREATE INDEX idx_chunk_tsv_ar ON doc_chunk USING gin (tsv_ar);

-- Metadata pre-filters applied before retrieval (§5.3 A6).
CREATE INDEX idx_chunk_lang     ON doc_chunk (lang);
CREATE INDEX idx_chunk_category ON doc_chunk (service_category);
CREATE INDEX idx_chunk_kind     ON doc_chunk (kind);
CREATE INDEX idx_chunk_meta     ON doc_chunk USING gin (metadata jsonb_path_ops);
"""

GRANTS = "GRANT SELECT ON doc_chunk TO masar_ro;"


def _vector_literal(vector) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vector) + "]"


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Masar AI — build hybrid search indexes")
    parser.add_argument("--rebuild-corpus", action="store_true", help="regenerate corpus markdown first")
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args(argv)

    settings = get_settings()

    if args.rebuild_corpus:
        from backend.ingestion.corpus import CorpusBuilder

        builder = CorpusBuilder(
            settings.gold_dir, settings.bronze_dir, settings.dq_report_dir, settings.corpus_dir
        )
        log.info("index.corpus_rebuilt", **{k: v for k, v in builder.build_all().items()})

    # ---- gather ------------------------------------------------------------
    chunks = chunk_corpus(settings.corpus_dir)
    summaries = row_summaries.build_all(settings.gold_dir)
    log.info("index.gathered", document_chunks=len(chunks), row_summaries=len(summaries))

    if not chunks and not summaries:
        log.error("index.nothing_to_index")
        return 1

    records: list[dict] = []

    for chunk in chunks:
        records.append(
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "kind": "document",
                "source_table": None,
                "row_key": None,
                "title": chunk.title,
                "heading_path": chunk.heading_path,
                "text": chunk.text,
                "raw_text": chunk.raw_text,
                "lang": chunk.lang,
                "service_category": chunk.service_category,
                "source_url": chunk.source_url,
                "retrieved_date": chunk.retrieved_date,
                "captured_at": None,
                "position": chunk.position,
                "token_estimate": chunk.token_estimate,
                "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
            }
        )

    for summary in summaries:
        # Arabic variants are indexed as their own rows so an Arabic query can
        # match them lexically, not only through the shared embedding space.
        for lang, text in (("en", summary.text_en), ("ar", summary.text_ar)):
            if not text:
                continue
            records.append(
                {
                    "chunk_id": f"{summary.summary_id}#{lang}",
                    "doc_id": summary.summary_id,
                    "kind": "row_summary",
                    "source_table": summary.table,
                    "row_key": summary.row_key,
                    "title": summary.table,
                    "heading_path": "",
                    "text": text,
                    "raw_text": text,
                    "lang": lang,
                    "service_category": "structured_fact",
                    "source_url": summary.source_url,
                    "retrieved_date": None,
                    "captured_at": summary.captured_at,
                    "position": 0,
                    "token_estimate": len(text.split()),
                    "metadata": json.dumps(summary.metadata, ensure_ascii=False, default=str),
                }
            )

    # ---- embed -------------------------------------------------------------
    log.info("index.embedding", records=len(records))
    vectors = embed_texts([r["text"] for r in records], batch_size=args.batch_size)
    log.info("index.embedded", shape=list(vectors.shape))

    # ---- load --------------------------------------------------------------
    with psycopg.connect(settings.pg_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

        with conn.cursor() as cur:
            for record, vector in zip(records, vectors, strict=True):
                arabic_source = record["text"] if record["lang"] == "ar" else ""
                cur.execute(
                    """
                    INSERT INTO doc_chunk (
                        chunk_id, doc_id, kind, source_table, row_key, title,
                        heading_path, text, raw_text, lang, service_category,
                        source_url, retrieved_date, captured_at, position,
                        token_estimate, metadata, embedding, tsv_en, tsv_ar
                    ) VALUES (
                        %(chunk_id)s, %(doc_id)s, %(kind)s, %(source_table)s, %(row_key)s,
                        %(title)s, %(heading_path)s, %(text)s, %(raw_text)s, %(lang)s,
                        %(service_category)s, %(source_url)s, %(retrieved_date)s,
                        %(captured_at)s, %(position)s, %(token_estimate)s,
                        %(metadata)s::jsonb, %(embedding)s::vector,
                        to_tsvector('english', %(text)s),
                        to_tsvector('simple', %(arabic_norm)s)
                    )
                    ON CONFLICT (chunk_id) DO NOTHING
                    """,
                    {
                        **record,
                        "embedding": _vector_literal(vector),
                        "arabic_norm": normalise_arabic(arabic_source),
                    },
                )
        conn.commit()

        log.info("index.building_indexes")
        with conn.cursor() as cur:
            cur.execute(INDEXES)
            cur.execute(GRANTS)
            cur.execute("ANALYZE doc_chunk")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kind, lang, COUNT(*) FROM doc_chunk
                GROUP BY kind, lang ORDER BY kind, lang
                """
            )
            breakdown = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM doc_chunk")
            total = cur.fetchone()[0]

    print("\n  PHASE 4 GATE — hybrid search index")
    print("  " + "─" * 56)
    print(f"  {'kind':<16} {'lang':<6} {'chunks':>8}")
    print("  " + "─" * 56)
    for kind, lang, count in breakdown:
        print(f"  {kind:<16} {lang:<6} {count:>8,}")
    print("  " + "─" * 56)
    print(f"  {total:,} chunks indexed · dense HNSW + lexical GIN (en, ar)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

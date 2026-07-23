"""Local embedding and reranking.

Both models run on-device. That is not only a cost decision: it means retrieval
quality does not degrade when a free API tier is exhausted, so the graceful
degradation story holds for the retrieval half of the system too — only
generation falls back.

`bge-m3` places Arabic and English in a genuinely shared space, so an Arabic
query retrieves English documents and vice versa. That property is what makes
bilingual retrieval work at all with an English-dominant corpus, and it is
verified by a test rather than assumed.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from backend.config.settings import get_model_config
from backend.services.logging import get_logger

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder, SentenceTransformer

log = get_logger(__name__)

_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _embedding_config() -> dict:
    return get_model_config()["local_models"]["embedding"]


@lru_cache(maxsize=1)
def _reranker_config() -> dict:
    return get_model_config()["local_models"]["reranker"]


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    """Load bge-m3 once per process. First call downloads ~2.1 GB."""
    from sentence_transformers import SentenceTransformer

    config = _embedding_config()
    with _LOCK:
        log.info("embedder.loading", model=config["name"])
        model = SentenceTransformer(config["name"])
        model.max_seq_length = min(int(config["max_seq_length"]), model.max_seq_length)
        log.info(
            "embedder.loaded",
            model=config["name"],
            dimensions=model.get_sentence_embedding_dimension(),
        )
        return model


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    from sentence_transformers import CrossEncoder

    config = _reranker_config()
    with _LOCK:
        log.info("reranker.loading", model=config["name"])
        model = CrossEncoder(config["name"], max_length=512)
        log.info("reranker.loaded", model=config["name"])
        return model


def embed_texts(texts: list[str], *, batch_size: int = 16) -> np.ndarray:
    """Embed for indexing. Returns L2-normalised vectors.

    Normalising here means cosine similarity is a dot product, which is what
    pgvector's `<=>` operator expects and what keeps the SQL simple.
    """
    if not texts:
        return np.zeros((0, int(_embedding_config()["dimensions"])), dtype=np.float32)

    model = get_embedder()
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return vectors.astype(np.float32)


def embed_query(text: str) -> np.ndarray:
    """Embed a single query.

    bge-m3 needs no query prefix — unlike the bge v1.5 family, which requires
    "Represent this sentence for searching relevant passages:". Adding one here
    would silently degrade retrieval.
    """
    return embed_texts([text])[0]


def rerank(
    query: str,
    passages: list[str],
    *,
    top_k: int | None = None,
    threshold: float | None = None,
) -> list[tuple[int, float]]:
    """Cross-encoder rerank. Returns `(original_index, score)`, best first.

    Passages below `threshold` are dropped even when that leaves fewer than
    `top_k`. A thin clean context beats a padded one — and the Grader (A12) is
    the component responsible for noticing genuine insufficiency, not the
    reranker.
    """
    if not passages:
        return []

    config = _reranker_config()
    top_k = top_k if top_k is not None else int(config["top_k"])
    threshold = threshold if threshold is not None else float(config["threshold"])

    model = get_reranker()
    scores = model.predict(
        [(query, passage) for passage in passages],
        batch_size=16,
        show_progress_bar=False,
    )

    ranked = sorted(enumerate(float(s) for s in scores), key=lambda p: p[1], reverse=True)
    kept = [(index, score) for index, score in ranked if score >= threshold][:top_k]

    log.info(
        "reranker.scored",
        candidates=len(passages),
        kept=len(kept),
        threshold=threshold,
        dropped_below_threshold=sum(1 for _, s in ranked if s < threshold),
    )
    return kept

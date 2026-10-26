"""Batch embedding service using BGE-base-en-v1.5.

Loads the model once and provides a simple batch interface.
Normalizes embeddings for cosine similarity in Qdrant.

BGE retrieval asymmetry: documents (passages) are embedded as-is, but a
short search *query* benefits from the recommended instruction prefix. Use
embed_query() for queries and embed_batch() for passages.
"""

from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from shared.config import settings

# Recommended retrieval instruction for BGE-* query embeddings. Improves
# recall on short queries; must NOT be applied to indexed passages.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

_model: "SentenceTransformer | None" = None
_model_lock = Lock()


def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(
                    settings.embedding_model, revision=settings.embedding_revision
                )
    return _model


def embed_batch(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """Embed a list of texts, returning normalized vectors.

    Processes in sub-batches of embedding_batch_size for memory efficiency.
    Set is_query=True to prepend the BGE retrieval instruction (queries only).
    """
    model = _get_model()
    if is_query:
        texts = [BGE_QUERY_INSTRUCTION + t for t in texts]

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), settings.embedding_batch_size):
        batch = texts[i : i + settings.embedding_batch_size]
        vectors = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_embeddings.extend(vectors.tolist())

    return all_embeddings


def embed_query(text: str) -> list[float]:
    """Embed a single search query (with the BGE query instruction)."""
    return embed_batch([text], is_query=True)[0]


def warmup() -> None:
    """Load the model and run one encode so the first request isn't slow."""
    embed_query("warmup")

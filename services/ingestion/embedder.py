"""Batch embedding service using BGE-base-en-v1.5.

Loads the model once and provides a simple batch interface.
Normalizes embeddings for cosine similarity in Qdrant.
"""

from sentence_transformers import SentenceTransformer

from shared.config import settings

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, returning normalized vectors.

    Processes in sub-batches of embedding_batch_size for memory efficiency.
    """
    model = _get_model()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), settings.embedding_batch_size):
        batch = texts[i : i + settings.embedding_batch_size]
        vectors = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_embeddings.extend(vectors.tolist())

    return all_embeddings

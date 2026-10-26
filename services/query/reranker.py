"""Cross-encoder reranker using ms-marco-MiniLM-L-6-v2.

Takes the merged retrieval results and re-scores each (query, chunk)
pair with a cross-encoder for more accurate relevance ranking.
"""

from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

from shared.config import settings
from shared.models import RetrievalResult

_model: "CrossEncoder | None" = None
_model_lock = Lock()


def _get_model() -> "CrossEncoder":
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder

        with _model_lock:
            if _model is None:
                _model = CrossEncoder(settings.reranker_model, revision=settings.reranker_revision)
    return _model


def rerank(
    query: str,
    results: list[RetrievalResult],
    top_k: int = 5,
) -> list[RetrievalResult]:
    """Re-score results with cross-encoder and return top-k."""
    if not results:
        return []

    model = _get_model()
    pairs = [(query, r.content) for r in results]
    scores = model.predict(pairs, show_progress_bar=False)

    scored = [
        result.model_copy(update={"score": float(score)})
        for result, score in zip(results, scores, strict=True)
    ]
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


def warmup() -> None:
    """Load the cross-encoder so the first request isn't slow."""
    _get_model().predict([("warmup query", "warmup document")], show_progress_bar=False)

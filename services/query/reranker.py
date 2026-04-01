"""Cross-encoder reranker using ms-marco-MiniLM-L-6-v2.

Takes the merged retrieval results and re-scores each (query, chunk)
pair with a cross-encoder for more accurate relevance ranking.
"""

from sentence_transformers import CrossEncoder

from shared.config import settings
from shared.models import RetrievalResult

_model: CrossEncoder | None = None


def _get_model() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(settings.reranker_model)
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
        for result, score in zip(results, scores)
    ]
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]

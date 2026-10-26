"""One filter contract for both retrieval backends."""

ALLOWED_FILTERS = frozenset({"corpus_id", "doc_type", "language", "source_path"})


def validate_filters(filters: dict[str, str] | None) -> dict[str, str]:
    filters = dict(filters or {})
    if set(filters) - ALLOWED_FILTERS:
        raise ValueError("Unsupported retrieval filter")
    if any(not isinstance(v, str) or not v or len(v) > 1024 for v in filters.values()):
        raise ValueError("Filter values must be nonempty strings up to 1024 characters")
    return filters

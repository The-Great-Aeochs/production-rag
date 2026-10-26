# Hybrid retrieval
Semantic vector search runs in Qdrant and keyword full-text search runs in PostgreSQL. The keyword ranker uses ts_rank_cd, not BM25. Both backends enforce corpus_id, source_path, doc_type, and language filters. Results are fused with Reciprocal Rank Fusion and reranked with a cross-encoder. Vector candidates are hydrated from ready database chunks before generation.

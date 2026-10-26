export const examples = [
  {
    question: "How does the system keep workspaces isolated?",
    answer:
      "Every query runs inside a server-selected corpus. Both semantic and keyword retrieval enforce that scope, and vector results are checked against published database chunks before they reach generation.",
    source: "retrieval.md",
    section: "Hybrid retrieval",
    excerpt:
      "Both backends enforce corpus_id, source_path, doc_type, and language filters. Vector candidates are hydrated from ready database chunks before generation.",
  },
  {
    question: "What happens if an ingestion worker crashes?",
    answer:
      "Jobs remain in Postgres. When the worker connection closes, its corpus lock is released. Another worker can retry the unfinished job; already-published documents with matching hashes are skipped.",
    source: "ingestion.md",
    section: "Durable ingestion",
    excerpt:
      "A crashed worker releases its lock when the database connection closes. An unfinished job is retried up to INGESTION_MAX_ATTEMPTS, then marked failed.",
  },
  {
    question: "Can cached answers leak between conversations?",
    answer:
      "Conversation answers are not stored in the shared response cache. Other cached answers are partitioned by identity, corpus, filters, model settings, and the corpus revision.",
    source: "cache.md",
    section: "Response cache",
    excerpt:
      "Cache keys include token owner, corpus filter, source filters, top_k, model names, prompt version, generation settings, and the corpus revision. Conversation answers are not cached.",
  },
];
export const repository = "https://github.com/The-Great-Aeochs/production-rag";

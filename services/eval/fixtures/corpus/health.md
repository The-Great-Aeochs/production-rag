# Health and monitoring
The /health/live route checks process liveness without contacting dependencies. The /health/ready route checks Postgres schema, Qdrant collection, Redis, the configured Ollama model, and local model warmup. A failed readiness check returns HTTP 503. The /metrics route requires an admin token and exposes request counts and duration histograms.

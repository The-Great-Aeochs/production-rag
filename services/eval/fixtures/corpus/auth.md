# Authentication
Queries require bearer tokens. The API_KEYS mapping assigns each query token to exactly one corpus. A separate ADMIN_API_KEY protects ingestion and metrics. Sessions belong to the token that created them. Foreign or expired sessions return HTTP 404. Requests cannot override their token corpus with a client filter.

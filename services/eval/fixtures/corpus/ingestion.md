# Durable ingestion
Ingestion jobs are stored in Postgres. Workers acquire session advisory locks for each corpus. A crashed worker releases its lock when the database connection closes. An unfinished job is retried up to INGESTION_MAX_ATTEMPTS, then marked failed. Each ingestion run snapshots the entire corpus root; subdirectory snapshots are rejected.

# Document publication
Postgres is the authoritative content store. Pending documents are hidden from retrieval until Qdrant and S3 writes succeed. Failed writes are retried even when their content hash is unchanged. Deletions first set a deleting tombstone, then remove external objects, then delete the database row. Original binary PDF bytes are preserved in object storage.

"""Test a configured private S3 bucket using one unique disposable object."""

import io
import uuid

from minio import Minio


def check_object_store(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        raise RuntimeError("The configured private bucket must be created first")
    key = f"_deployment-check/{uuid.uuid4().hex}.txt"
    payload = b"production-rag object-store deployment check\n"
    try:
        client.put_object(bucket, key, io.BytesIO(payload), len(payload), content_type="text/plain")
        response = client.get_object(bucket, key)
        try:
            if response.read(len(payload) + 1) != payload:
                raise RuntimeError("Object-store round trip returned unexpected bytes")
        finally:
            response.close()
            response.release_conn()
    finally:
        # Only this invocation's UUID key is eligible for cleanup, even when a
        # timeout leaves the outcome of a put uncertain. Never list/delete data.
        client.remove_object(bucket, key)


def main() -> int:
    from shared.config import settings
    from shared.db import get_minio

    client = get_minio()
    try:
        check_object_store(client, settings.minio_bucket)
    except Exception as exc:
        print(f"FAIL object store ({type(exc).__name__}); check endpoint, region, and permissions.")
        print("If cleanup failed, remove only the test objects under _deployment-check/.")
        return 1
    print("PASS object store: bucket exists; test object written, read back, and removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

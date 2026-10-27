import io

import pytest
import urllib3

from scripts.check_object_store import check_object_store
from shared import db
from shared.config import settings


class Store:
    def __init__(self, *, fail_put=False, wrong_payload=False):
        self.objects = {"existing-document": b"preserve"}
        self.removed = []
        self.response = None
        self.fail_put = fail_put
        self.wrong_payload = wrong_payload

    def bucket_exists(self, bucket):
        return True

    def put_object(self, bucket, key, stream, size, **kwargs):
        self.objects[key] = stream.read()
        if self.fail_put:
            raise TimeoutError("Uncertain write outcome")

    def get_object(self, bucket, key):
        self.response = io.BytesIO(b"wrong" if self.wrong_payload else self.objects[key])
        self.response.release_conn = lambda: None
        return self.response

    def remove_object(self, bucket, key):
        self.removed.append(key)
        self.objects.pop(key, None)


def test_object_store_check_round_trips_and_removes_only_its_test_object():
    store = Store()
    check_object_store(store, "raw-docs")
    assert store.objects == {"existing-document": b"preserve"}
    assert len(store.removed) == 1 and store.removed[0].startswith("_deployment-check/")
    assert store.response.closed


@pytest.mark.parametrize("failure", ["fail_put", "wrong_payload"])
def test_object_store_check_cleans_up_partial_writes_and_failed_reads(failure):
    store = Store(**{failure: True})
    with pytest.raises((RuntimeError, TimeoutError)):
        check_object_store(store, "raw-docs")
    assert store.objects == {"existing-document": b"preserve"}
    assert len(store.removed) == 1


def test_missing_bucket_is_not_automatically_created():
    store = Store()
    store.bucket_exists = lambda _: False
    with pytest.raises(RuntimeError, match="created first"):
        check_object_store(store, "raw-docs")
    assert store.removed == []


def test_oci_signing_uses_explicit_region_and_path_style_without_region_discovery(monkeypatch):
    requests = []

    class Transport(urllib3.PoolManager):
        def urlopen(self, method, url, **kwargs):
            requests.append((method, url, kwargs["headers"]))
            return urllib3.HTTPResponse(
                status=200,
                headers={"etag": '"test-etag"', "content-length": "0"},
                body=b"",
            )

    monkeypatch.setattr(db.urllib3, "PoolManager", Transport)
    monkeypatch.setattr(
        settings, "minio_endpoint", "testnamespace.compat.objectstorage.ap-mumbai-1.oraclecloud.com"
    )
    monkeypatch.setattr(settings, "minio_region", "ap-mumbai-1")
    monkeypatch.setattr(settings, "minio_root_user", "test-access-key")
    monkeypatch.setattr(settings, "minio_root_password", "test-secret-key")
    monkeypatch.setattr(settings, "minio_secure", True)
    client = db.get_minio()
    try:
        client.put_object("raw-docs", "test.txt", io.BytesIO(b"test"), 4)
    finally:
        client._http.clear()
    assert len(requests) == 1
    method, url, headers = requests[0]
    assert method == "PUT"
    assert (
        url
        == "https://testnamespace.compat.objectstorage.ap-mumbai-1.oraclecloud.com/raw-docs/test.txt"
    )
    assert "/ap-mumbai-1/s3/aws4_request" in headers["Authorization"]

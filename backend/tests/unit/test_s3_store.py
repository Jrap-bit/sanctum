"""Unit tests for the S3 object store against an in-memory fake client."""
from io import BytesIO

import boto3
import pytest
from botocore.exceptions import ClientError

from app.adapters.objectstore import S3Store
from app.adapters.registry import object_stores
from app.core.config import get_settings


def client_error(code, status, operation="Operation"):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, operation)


class FakeS3:
    def __init__(self, bucket_exists=True):
        self.buckets = {"sanctum-test"} if bucket_exists else set()
        self.objects = {}
        self.calls = []
        self.fail_with = {}

    def _record(self, name):
        self.calls.append(name)
        if name in self.fail_with:
            raise self.fail_with[name]

    def head_bucket(self, Bucket):
        self._record("head_bucket")
        if Bucket not in self.buckets:
            raise client_error("404", 404, "HeadBucket")

    def create_bucket(self, Bucket):
        self._record("create_bucket")
        self.buckets.add(Bucket)

    def put_object(self, Bucket, Key, Body, ContentType):
        self._record("put_object")
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, Bucket, Key):
        self._record("get_object")
        if (Bucket, Key) not in self.objects:
            raise client_error("NoSuchKey", 404, "GetObject")
        return {"Body": BytesIO(self.objects[(Bucket, Key)][0])}

    def head_object(self, Bucket, Key):
        self._record("head_object")
        if (Bucket, Key) not in self.objects:
            raise client_error("404", 404, "HeadObject")

    def delete_object(self, Bucket, Key):
        self._record("delete_object")
        self.objects.pop((Bucket, Key), None)


@pytest.fixture
def s3(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "s3_bucket", "sanctum-test")
    monkeypatch.setattr(settings, "s3_endpoint_url", "")
    monkeypatch.setattr(settings, "s3_region", "ap-south-1")
    monkeypatch.setattr(settings, "s3_access_key", "AKIDEXAMPLE")
    monkeypatch.setattr(settings, "s3_secret_key", None)
    fake = FakeS3()
    created = []

    def client(service, **kwargs):
        created.append((service, kwargs))
        return fake

    monkeypatch.setattr(boto3, "client", client)
    fake.created = created
    return fake


@pytest.mark.unit
def test_client_built_from_settings(s3):
    S3Store()
    assert s3.created == [("s3", {"endpoint_url": None, "region_name": "ap-south-1",
                                  "aws_access_key_id": "AKIDEXAMPLE", "aws_secret_access_key": None})]


@pytest.mark.unit
def test_registry_builds_s3_store(s3):
    assert isinstance(object_stores.create("s3"), S3Store)


@pytest.mark.unit
def test_put_get_exists_delete_round_trip(s3):
    store = S3Store()
    key = "patients/p1/documents/d1/original"
    store.put(key, b"ciphertext", "application/octet-stream")
    assert s3.objects[("sanctum-test", key)] == (b"ciphertext", "application/octet-stream")
    assert store.exists(key)
    assert store.get(key) == b"ciphertext"
    store.delete(key)
    assert not store.exists(key)


@pytest.mark.unit
def test_bucket_checked_once_and_created_when_missing(monkeypatch, s3):
    s3.buckets.clear()
    store = S3Store()
    store.put("a", b"1", "text/plain")
    store.put("b", b"2", "text/plain")
    store.exists("a")
    assert s3.calls.count("head_bucket") == 1
    assert s3.calls.count("create_bucket") == 1
    assert "sanctum-test" in s3.buckets


@pytest.mark.unit
def test_bucket_creation_failure_is_tolerated(s3):
    s3.buckets.clear()
    s3.fail_with["create_bucket"] = client_error("BucketAlreadyOwnedByYou", 409)
    store = S3Store()
    store.put("a", b"1", "text/plain")
    assert ("sanctum-test", "a") in s3.objects


@pytest.mark.unit
def test_get_missing_object_raises_file_not_found(s3):
    with pytest.raises(FileNotFoundError, match="missing"):
        S3Store().get("missing")


@pytest.mark.unit
def test_get_404_with_unusual_code_raises_file_not_found(s3):
    s3.fail_with["get_object"] = client_error("NotFound", 404)
    with pytest.raises(FileNotFoundError):
        S3Store().get("anything")


@pytest.mark.unit
def test_get_other_errors_propagate(s3):
    s3.fail_with["get_object"] = client_error("AccessDenied", 403)
    with pytest.raises(ClientError):
        S3Store().get("anything")


@pytest.mark.unit
def test_exists_other_errors_propagate(s3):
    s3.fail_with["head_object"] = client_error("AccessDenied", 403)
    with pytest.raises(ClientError):
        S3Store().exists("anything")


@pytest.mark.parametrize("method,args", [("put", (b"x", "text/plain")), ("get", ()), ("delete", ()), ("exists", ())])
@pytest.mark.parametrize("key", ["../escape", "a/../b", "/absolute", "", "bad key"])
@pytest.mark.unit
def test_invalid_keys_rejected_before_any_request(s3, method, args, key):
    with pytest.raises(ValueError):
        getattr(S3Store(), method)(key, *args)
    assert s3.calls == []

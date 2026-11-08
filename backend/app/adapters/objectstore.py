import os
from pathlib import Path
import re
from uuid import uuid4

from ..core.config import get_settings
from .registry import object_stores

KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]*$")


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not KEY_PATTERN.match(key) or any(seg == ".." for seg in key.split("/")):
        raise ValueError(f"Invalid object key: {key}")


class FilesystemStore:
    name = "filesystem"

    def __init__(self):
        self.root = get_settings().store_path

    def _resolve(self, key: str) -> Path:
        _validate_key(key)
        target = (self.root / key).resolve()
        root_resolved = self.root.resolve()
        if not target.is_relative_to(root_resolved):
            raise ValueError(f"Path traversal detected: {key}")
        return target

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        temp_path = path.parent / f"tmp-{uuid4().hex}"
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def get(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            with open(path, "rb") as f:
                return f.read()
        except (FileNotFoundError, IsADirectoryError):
            raise FileNotFoundError(f"Object not found: {key}") from None

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def exists(self, key: str) -> bool:
        path = self._resolve(key)
        return path.is_file()


class S3Store:
    name = "s3"

    def __init__(self):
        import boto3
        from botocore.exceptions import ClientError
        self._ClientError = ClientError
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        self._bucket_checked = False

    def _ensure_bucket(self):
        if not self._bucket_checked:
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except self._ClientError:
                try:
                    self.client.create_bucket(Bucket=self.bucket)
                except self._ClientError:
                    pass
            self._bucket_checked = True

    def put(self, key: str, data: bytes, content_type: str) -> None:
        _validate_key(key)
        self._ensure_bucket()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        _validate_key(key)
        self._ensure_bucket()
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except self._ClientError as e:
            code = str(e.response.get("Error", {}).get("Code", ""))
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code == "NoSuchKey" or status == 404:
                raise FileNotFoundError(f"Object not found: {key}") from None
            raise

    def delete(self, key: str) -> None:
        _validate_key(key)
        self._ensure_bucket()
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        _validate_key(key)
        self._ensure_bucket()
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self._ClientError as e:
            code = str(e.response.get("Error", {}).get("Code", ""))
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in ("NoSuchKey", "404") or status == 404:
                return False
            raise


_store = None


def get_store():
    global _store
    if _store is None:
        _store = object_stores.create(get_settings().store_backend)
    return _store


def reset_store() -> None:
    global _store
    _store = None

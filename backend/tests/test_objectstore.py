import pytest

from app.adapters.objectstore import FilesystemStore
from app.adapters.registry import object_stores
from app.core.exceptions import AdapterConfigurationError
from test_patients import setup


def test_filesystem_store_put_get_exists_delete_and_idempotent(setup):
    store = FilesystemStore()
    key = "patients/p1/documents/d1/original"
    data = b"synthetic protected document"

    assert not store.exists(key)
    store.put(key, data, "application/octet-stream")
    assert store.exists(key)
    assert store.get(key) == data

    store.delete(key)
    assert not store.exists(key)

    # Idempotent delete: deleting absent key should not raise
    store.delete(key)
    assert not store.exists(key)


def test_filesystem_store_missing_get_raises_file_not_found(setup):
    store = FilesystemStore()
    with pytest.raises(FileNotFoundError):
        store.get("patients/missing/documents/missing/original")


@pytest.mark.parametrize(
    "invalid_key",
    [
        "../traversal",
        "patients/../../traversal",
        "folder/../escape",
        "..",
        "/absolute/path",
        "",
        "invalid char *",
        "invalid?",
    ],
)
def test_filesystem_store_path_traversal_and_invalid_keys_rejected(setup, invalid_key):
    store = FilesystemStore()
    with pytest.raises(ValueError):
        store.put(invalid_key, b"data", "text/plain")

    with pytest.raises(ValueError):
        store.get(invalid_key)

    with pytest.raises(ValueError):
        store.delete(invalid_key)

    with pytest.raises(ValueError):
        store.exists(invalid_key)


def test_unknown_backend_name_raises_adapter_configuration_error():
    with pytest.raises(AdapterConfigurationError):
        object_stores.create("unknown_store_backend")

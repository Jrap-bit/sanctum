import os
import stat
import pytest

from app.adapters.crypto import (
    decrypt,
    decrypt_bytes,
    encrypt,
    encrypt_bytes,
    initialize_key,
    reload_keys,
    rotate_key,
)
from app.core.config import get_settings
from app.core.exceptions import CiphertextIntegrityError, KeyUnavailableError
from test_patients import setup


def test_round_trip_dict_and_bytes(setup):
    data_dict = {"patient_id": "123", "notes": "Observation text", "tags": [1, 2, 3]}
    ct_dict = encrypt(data_dict, "context:patient:123")
    assert decrypt(ct_dict, "context:patient:123") == data_dict

    data_bytes = b"sample document raw bytes \x00\x01\xfe\xff"
    ct_bytes = encrypt_bytes(data_bytes, "context:doc:456")
    assert decrypt_bytes(ct_bytes, "context:doc:456") == data_bytes


def test_flipped_ciphertext_byte_raises_integrity_error(setup):
    ct = encrypt({"key": "val"}, "context:sample")
    corrupted = bytearray(ct)
    corrupted[-1] ^= 0x01
    with pytest.raises(CiphertextIntegrityError):
        decrypt(bytes(corrupted), "context:sample")

    ct_bytes = encrypt_bytes(b"binary data", "context:sample")
    corrupted_bytes = bytearray(ct_bytes)
    corrupted_bytes[-1] ^= 0x01
    with pytest.raises(CiphertextIntegrityError):
        decrypt_bytes(bytes(corrupted_bytes), "context:sample")


def test_wrong_context_raises_integrity_error(setup):
    ct = encrypt({"key": "val"}, "context:expected")
    with pytest.raises(CiphertextIntegrityError):
        decrypt(ct, "context:wrong")

    ct_bytes = encrypt_bytes(b"payload", "context:expected")
    with pytest.raises(CiphertextIntegrityError):
        decrypt_bytes(ct_bytes, "context:wrong")


def test_decrypting_under_different_data_key_file_raises_integrity_error(setup, tmp_path, monkeypatch):
    ct = encrypt({"secret": "data"}, "context:test")

    other_keys_path = tmp_path / "other-keys.json"
    monkeypatch.setattr(get_settings(), "wrapped_keys_path", other_keys_path)
    reload_keys()
    initialize_key()

    with pytest.raises(CiphertextIntegrityError):
        decrypt(ct, "context:test")


def test_missing_master_key_raises_key_unavailable_error(setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "master_key", None)
    get_settings().master_key_path.unlink()
    reload_keys()

    with pytest.raises(KeyUnavailableError):
        encrypt({"a": 1}, "ctx")

    with pytest.raises(KeyUnavailableError):
        decrypt_bytes(b"SNCTM1k001" + b"\x00" * 28, "ctx")


def test_two_encryptions_of_same_input_differ(setup):
    ct1 = encrypt({"same": "content"}, "ctx")
    ct2 = encrypt({"same": "content"}, "ctx")
    assert ct1 != ct2

    ct1_b = encrypt_bytes(b"same content", "ctx")
    ct2_b = encrypt_bytes(b"same content", "ctx")
    assert ct1_b != ct2_b


def test_rotate_key_preserves_old_decryption_and_uses_new_id(setup):
    old_ct = encrypt({"version": 1}, "ctx")
    assert old_ct[6:10] == b"k001"

    new_id = rotate_key()
    assert new_id == "k002"

    new_ct = encrypt({"version": 2}, "ctx")
    assert new_ct[6:10] == b"k002"

    assert decrypt(old_ct, "ctx") == {"version": 1}
    assert decrypt(new_ct, "ctx") == {"version": 2}


def test_initialize_key_twice_leaves_file_unchanged(setup):
    master_path = get_settings().master_key_path
    wrapped_path = get_settings().wrapped_keys_path

    master_content = master_path.read_bytes()
    wrapped_content = wrapped_path.read_bytes()

    initialize_key()

    assert master_path.read_bytes() == master_content
    assert wrapped_path.read_bytes() == wrapped_content


def test_key_file_modes_are_0o600(setup):
    master_stat = os.stat(get_settings().master_key_path)
    wrapped_stat = os.stat(get_settings().wrapped_keys_path)

    assert stat.S_IMODE(master_stat.st_mode) == 0o600
    assert stat.S_IMODE(wrapped_stat.st_mode) == 0o600

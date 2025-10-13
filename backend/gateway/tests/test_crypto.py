import pytest

from backend.gateway.app import crypto


@pytest.fixture()
def sample_key() -> bytes:
    return b"\x01" * 32


def test_encrypt_decrypt_round_trip(sample_key):
    plaintext = "super-secret"
    associated_data = b"metadata"

    encrypted = crypto.encrypt(plaintext, key=sample_key, associated_data=associated_data)

    assert isinstance(encrypted, bytes)
    assert encrypted != plaintext.encode()

    decrypted = crypto.decrypt(encrypted, key=sample_key, associated_data=associated_data)
    assert decrypted == plaintext.encode()


def test_encrypt_uses_unique_nonce(sample_key):
    payload = b"payload"
    first = crypto.encrypt(payload, key=sample_key)
    second = crypto.encrypt(payload, key=sample_key)

    assert first != second
    assert len(first) == len(second)


@pytest.mark.parametrize(
    "value,prefix,suffix,expected",
    [
        ("abcd1234", 2, 2, "AB…34"),
        ("short", 4, 4, "SHORT"),
        ("  ", 4, 4, ""),
    ],
)
def test_mask_key(value, prefix, suffix, expected):
    assert crypto.mask_key(value, prefix=prefix, suffix=suffix) == expected

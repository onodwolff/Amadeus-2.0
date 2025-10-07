"""Unit tests covering the API keys CRUD workflow."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.gateway.db.models import ApiKey, User, UserRole


@pytest.mark.asyncio
async def test_api_keys_crud_encryption_roundtrip(db_session, session_factory, monkeypatch):
    """API key secrets should survive a full create/update/delete cycle."""

    from backend.gateway.app.routes import keys

    # Seed a primary user required by the API layer.
    user = User(
        email="alice@example.com",
        username="alice",
        name="Alice",
        pwd_hash="argon2$dummy",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()

    monkeypatch.setattr(keys.svc, "list_available_exchanges", lambda: {"exchanges": []})

    create_payload = keys.KeyCreateRequest(
        keyId="primary-key",
        venue="binance",
        label="Main trading key",
        scopes=["trade:write", "trade:read"],
        apiKey="TEST-ACCESS-KEY",
        secret=keys.EncryptedKeySecret(
            algorithm="AES-256-GCM",
            ciphertext="CAFEBABE",
            iv="INITVECTOR",
            salt="SALT",
            iterations=120000,
            kdf="PBKDF2",
            hash="SHA256",
        ),
        passphraseHash="passphrase-1",
        passphraseHint="first pet",
    )

    created = await keys.create_api_key(payload=create_payload, session=db_session)

    assert created.key_id == "primary-key"
    assert created.venue == "BINANCE"
    assert created.api_key_masked.endswith("KEY")
    assert created.fingerprint == "-KEY"

    # Verify the secret is encrypted in storage but decrypts to the original payload.
    verify_session = session_factory()
    try:
        result = await verify_session.execute(
            select(ApiKey).where(ApiKey.key_id == create_payload.key_id)
        )
        record = result.scalar_one()
        assert record.api_key_masked == created.api_key_masked
        secret_payload = keys._decode_secret_payload(record.secret_enc)
        assert secret_payload["api_key"] == create_payload.api_key
        assert secret_payload["passphrase_hint"] == create_payload.passphrase_hint
    finally:
        await verify_session.close()

    update_payload = keys.KeyUpdateRequest(
        venue="binance",
        label="Rotated key",
        scopes=["trade:write"],
        apiKey="ROTATED-KEY",
        secret=keys.EncryptedKeySecret(
            algorithm="AES-256-GCM",
            ciphertext="DEADBEEF",
            iv="NEWVECTOR",
            salt="NEWSALT",
            iterations=130000,
            kdf="PBKDF2",
            hash="SHA256",
        ),
        passphraseHash=create_payload.passphrase_hash,
        passphraseHint="updated pet",
    )

    updated = await keys.update_api_key(
        key_id=create_payload.key_id,
        payload=update_payload,
        session=db_session,
    )

    assert updated.label == "Rotated key"
    assert updated.fingerprint == "-KEY"
    assert updated.passphrase_hint == "updated pet"

    verify_session = session_factory()
    try:
        result = await verify_session.execute(
            select(ApiKey).where(ApiKey.key_id == create_payload.key_id)
        )
        record = result.scalar_one()
        secret_payload = keys._decode_secret_payload(record.secret_enc)
        assert secret_payload["api_key"] == "ROTATED-KEY"
        assert secret_payload["passphrase_hint"] == "updated pet"
    finally:
        await verify_session.close()

    delete_payload = keys.KeyDeleteRequest(passphraseHash=create_payload.passphrase_hash)
    await keys.delete_api_key(
        key_id=create_payload.key_id,
        payload=delete_payload,
        session=db_session,
    )

    verify_session = session_factory()
    try:
        result = await verify_session.execute(
            select(ApiKey).where(ApiKey.key_id == create_payload.key_id)
        )
        assert result.scalar_one_or_none() is None
    finally:
        await verify_session.close()

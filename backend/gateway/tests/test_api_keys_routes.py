from __future__ import annotations

import asyncio
import base64
import hashlib
import os

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.config import settings
from backend.gateway.app.dependencies import get_current_user
from backend.gateway.app.nautilus_engine_service import NautilusEngineService
from backend.gateway.db import models as db_models
from backend.gateway.db.base import Base as GatewayBase
from backend.gateway.db.models import UserRole

from .utils import create_user


def _encrypt_secret(secret: str, passphrase: str) -> dict[str, str]:
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100_000)
    key = kdf.derive(passphrase.encode("utf-8"))
    cipher = AESGCM(key)
    ciphertext = cipher.encrypt(iv, secret.encode("utf-8"), None)
    return {
        "algorithm": "AES-GCM",
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
        "iv": base64.b64encode(iv).decode("utf-8"),
        "salt": base64.b64encode(salt).decode("utf-8"),
        "iterations": 100_000,
        "kdf": "PBKDF2",
        "hash": "SHA-256",
    }


def _hash_passphrase(passphrase: str) -> str:
    return hashlib.sha256(passphrase.encode("utf-8")).hexdigest()


# Ensure test metadata does not carry PostgreSQL schemas when using SQLite
GatewayBase.metadata.schema = None
for table in GatewayBase.metadata.tables.values():
    table.schema = None

db_models.Base.metadata.schema = None
for table in db_models.Base.metadata.tables.values():
    table.schema = None


@pytest.mark.asyncio
async def test_api_key_crud_flow(app, db_session, db_engine, caplog):
    user = await create_user(
        db_session,
        email="member@example.com",
        username="member",
        password="secret-pass",
        roles=[UserRole.MEMBER.value],
    )

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        from backend.gateway.app import nautilus_engine_service as nes

        assert db_models.ApiKey.__table__.schema is None
        assert nes.create_async_engine is not None
        assert nes.async_sessionmaker is not None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            passphrase = "correct horse battery staple"
            passphrase_hash = _hash_passphrase(passphrase)
            secret_payload = _encrypt_secret("hunter2", passphrase)

            create_payload = {
                "keyId": "binance-primary",
                "venue": "BINANCE",
                "apiKey": "abc123xyz789",
                "scopes": ["trade", "read"],
                "secret": secret_payload,
                "passphraseHash": passphrase_hash,
                "label": "Primary key",
                "passphraseHint": "Trading desk",
            }

            create_response = await client.post("/keys", json=create_payload)
            assert create_response.status_code == 201
            created_key = create_response.json()
            assert created_key["key_id"] == "binance-primary"
            assert created_key["venue"] == "BINANCE"
            assert created_key["label"] == "Primary key"
            assert created_key["passphrase_hint"] == "Trading desk"
            assert created_key["api_key_masked"].startswith("ABC1")

            list_response = await client.get("/keys")
            assert list_response.status_code == 200
            keys_payload = list_response.json()
            assert len(keys_payload["keys"]) == 1

            updated_secret = _encrypt_secret("rotated-secret", passphrase)
            update_payload = {
                "venue": "Binance",  # ensure trimming/normalisation occurs
                "scopes": ["read", "trade", "trade"],
                "passphraseHash": passphrase_hash,
                "label": "Rotated key",
                "apiKey": "rotated987654",  # update masked value
                "secret": updated_secret,
                "passphraseHint": "Ops desk",
            }
            update_response = await client.put("/keys/binance-primary", json=update_payload)
            assert update_response.status_code == 200
            updated_key = update_response.json()
            assert updated_key["label"] == "Rotated key"
            assert updated_key["venue"] == "Binance"
            assert set(updated_key["scopes"]) == {"read", "trade"}
            assert updated_key["api_key_masked"].startswith("ROTA")
            assert updated_key["passphrase_hint"] == "Ops desk"

            caplog.set_level("DEBUG")
            service = NautilusEngineService(
                database_url=str(db_engine.url),
                encryption_key=settings.security.encryption_key_bytes,
            )
            credentials = await asyncio.to_thread(
                service._load_api_key_credentials,
                "binance-primary",
                str(user.id),
            )
            assert credentials is not None
            assert credentials["api_key"] == "rotated987654"
            assert credentials["api_secret"] == updated_secret
            assert credentials["passphrase_hash"] == passphrase_hash
            assert credentials["passphrase_hint"] == "Ops desk"

            delete_response = await client.request(
                "DELETE",
                "/keys/binance-primary",
                json={"passphraseHash": passphrase_hash},
            )
            assert delete_response.status_code == 204

            final_list = await client.get("/keys")
            assert final_list.status_code == 200
            assert final_list.json()["keys"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_api_key_passphrase_validation(app, db_session):
    user = await create_user(
        db_session,
        email="owner@example.com",
        username="owner",
        password="secret-pass",
        roles=[UserRole.MEMBER.value],
    )

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        from backend.gateway.app import nautilus_engine_service as nes

        assert db_models.ApiKey.__table__.schema is None
        assert nes.create_async_engine is not None
        assert nes.async_sessionmaker is not None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            passphrase = "valid passphrase"
            correct_hash = _hash_passphrase(passphrase)
            secret_payload = _encrypt_secret("hunter2", passphrase)

            create_response = await client.post(
                "/keys",
                json={
                    "keyId": "ftx-primary",
                    "venue": "FTX",
                    "apiKey": "secret-key",
                    "scopes": ["trade"],
                    "secret": secret_payload,
                    "passphraseHash": correct_hash,
                },
            )
            assert create_response.status_code == 201

            wrong_hash = _hash_passphrase("wrong passphrase")

            update_response = await client.put(
                "/keys/ftx-primary",
                json={
                    "venue": "FTX",
                    "scopes": ["trade"],
                    "passphraseHash": wrong_hash,
                },
            )
            assert update_response.status_code == 403
            assert update_response.json()["detail"] == "Invalid passphrase"

            delete_response = await client.request(
                "DELETE",
                "/keys/ftx-primary",
                json={"passphraseHash": wrong_hash},
            )
            assert delete_response.status_code == 403
            assert delete_response.json()["detail"] == "Invalid passphrase"

            final_list = await client.get("/keys")
            assert len(final_list.json()["keys"]) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)

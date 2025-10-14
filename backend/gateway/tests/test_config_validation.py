"""Validation tests for gateway configuration models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.gateway.app.config import AuthSettings


def test_auth_settings_defaults_within_bounds() -> None:
    settings = AuthSettings()

    assert settings.access_token_ttl_seconds == 900
    assert settings.refresh_token_ttl_seconds == 1_209_600
    assert settings.mfa_challenge_token_ttl_seconds == 300


@pytest.mark.parametrize(
    "value",
    [299, 901],
)
def test_access_token_ttl_out_of_bounds(value: int) -> None:
    with pytest.raises(ValidationError):
        AuthSettings(access_token_ttl_seconds=value)


@pytest.mark.parametrize(
    "value",
    [604_799, 2_592_001],
)
def test_refresh_token_ttl_out_of_bounds(value: int) -> None:
    with pytest.raises(ValidationError):
        AuthSettings(refresh_token_ttl_seconds=value)


@pytest.mark.parametrize(
    "value",
    [59, 901],
)
def test_mfa_challenge_ttl_out_of_bounds(value: int) -> None:
    with pytest.raises(ValidationError):
        AuthSettings.model_validate({"AUTH_MFA_CHALLENGE_TTL_SECONDS": value})

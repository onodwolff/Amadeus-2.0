"""Regression tests for the 0004_auth_users migration helpers."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import ProgrammingError

migration = importlib.import_module(
    "backend.gateway.alembic.versions.0004_auth_users"
)


class _DummyResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _DummyBind:
    def __init__(self, *, has_extension: bool, allow_create: bool) -> None:
        self._has_extension = has_extension
        self._allow_create = allow_create
        self.dialect = SimpleNamespace(name="postgresql")

    def exec_driver_sql(self, sql: str):
        if "CREATE EXTENSION" in sql:
            if not self._allow_create:
                raise ProgrammingError(
                    sql,
                    None,
                    SimpleNamespace(pgcode="42501"),
                )
            self._has_extension = True
            return _DummyResult(True)

        if "SELECT EXISTS" in sql:
            return _DummyResult(self._has_extension)

        raise AssertionError(f"Unexpected SQL: {sql}")


@pytest.mark.parametrize(
    "has_extension, allow_create, expected",
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
    ],
)
def test_ensure_citext_extension_reports_availability(
    has_extension: bool, allow_create: bool, expected: bool
) -> None:
    """The helper returns True only when the extension can be used."""

    bind = _DummyBind(has_extension=has_extension, allow_create=allow_create)

    result = migration._ensure_citext_extension(bind)

    assert result is expected

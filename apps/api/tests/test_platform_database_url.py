"""A platform-injected `DATABASE_URL` is adopted (and its driver renamed).

`fly postgres attach` sets `DATABASE_URL` on the app, as does every other
platform that has ever attached a database. Requiring an operator to copy
it into `VEC_DATABASE_URL` by hand, renaming the driver as they go, is a
step that exists only to be got wrong — and on a phone there is no shell
to do it in.
"""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("VEC_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.mark.parametrize(
    ("injected", "expected"),
    [
        # `postgres://` has not been a valid SQLAlchemy scheme since 1.4,
        # and it is exactly what platforms write.
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        # Already named: left alone.
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_the_driver_is_named_for_sqlalchemy(monkeypatch, injected, expected):
    monkeypatch.setenv("DATABASE_URL", injected)
    assert Settings().database_url == expected


def test_our_own_setting_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://platform/db")
    monkeypatch.setenv("VEC_DATABASE_URL", "postgresql+psycopg://ours/db")
    assert Settings().database_url == "postgresql+psycopg://ours/db"


def test_nothing_injected_leaves_the_default(monkeypatch):
    assert Settings().database_url.startswith("sqlite")


def test_an_empty_injection_is_ignored(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert Settings().database_url.startswith("sqlite")

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "benchmarks"))

# Set before anything imports app.config: Settings is cached per process.
os.environ.setdefault("VEC_ENVIRONMENT", "test")


@pytest.fixture(scope="session")
def fixtures():
    import fixtures as fx

    return fx


@pytest.fixture()
def tmp_env(tmp_path: Path) -> Iterator[Path]:
    """A fresh database and object store per test.

    SQLite plus the local storage backend, so the whole request path runs
    with no database server, no Redis and no cloud credentials.
    """
    from app import db, ratelimit, storage
    from app.config import settings

    db_path = tmp_path / "test.db"
    store_path = tmp_path / "storage"
    os.environ["VEC_DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["VEC_STORAGE_BACKEND"] = "local"
    os.environ["VEC_STORAGE_LOCAL_DIR"] = str(store_path)
    os.environ["VEC_ENVIRONMENT"] = "test"

    settings.cache_clear()
    db.reset()
    storage.reset_storage()
    ratelimit.reset()

    from app.models import Base

    Base.metadata.create_all(db.engine())
    yield tmp_path

    db.reset()
    storage.reset_storage()
    ratelimit.reset()
    settings.cache_clear()


@pytest.fixture()
def client(tmp_env):
    """TestClient with the worker running inline.

    The engine really runs: these are integration tests, and a mocked
    pipeline would not catch the two things most likely to break — the
    worker/API contract and the unlock gate on real output.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.queue import InlineDispatcher, set_dispatcher

    set_dispatcher(InlineDispatcher())
    with TestClient(app) as test_client:
        yield test_client
    set_dispatcher(None)


@pytest.fixture()
def session(tmp_env):
    from app.db import session_factory

    with session_factory()() as s:
        yield s


@pytest.fixture()
def user(session):
    from app.models import User

    record = User(id="usr_test", email="buyer@example.com", plan="starter")
    session.add(record)
    session.commit()
    return record


@pytest.fixture()
def auth(user):
    """A bearer token for `user`, signed with the dev secret."""
    import jwt

    from app.config import settings

    token = jwt.encode(
        {"sub": user.id, "email": user.email}, settings().jwt_dev_secret, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def logo_png(fixtures) -> bytes:
    return fixtures.by_name("logo_flat_small").data


def upload_and_vectorize(client, headers, data: bytes, options=None, **kwargs):
    """Helper: presigned upload → PUT → vectorize."""
    created = client.post(
        "/v1/uploads",
        json={"content_type": "image/png", "content_length": len(data)},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    slot = created.json()
    put = client.put(slot["put_url"], content=data, headers={"Content-Type": "image/png"})
    assert put.status_code == 200, put.text
    body = {"upload_id": slot["upload_id"], "options": options or {}}
    return client.post("/v1/vectorize", json=body, headers=headers, **kwargs)

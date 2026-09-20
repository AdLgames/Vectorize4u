"""Rows a caller is told about must be committed before it is told (§13).

`get_session` commits in its teardown, which FastAPI runs *after* the
response has been handed to the transport. A client that immediately uses
what the response gave it — an upload id, a batch id, an API key — can
therefore beat its own row into the database and get a 404 for something
it correctly created.

Under the test client this never happens: it serialises everything, so the
teardown has always run by the time the next call starts. It took the §13
load run, with a real server and a real broker, to see it — a preview 404
for an upload that was sitting in the uploads table the whole time.

These tests remove the safety net. The session they inject never commits
in its teardown, so anything that relies on the teardown fails here.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def client_without_teardown_commit(tmp_env):
    """A client whose request sessions are *never* committed for it."""
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.db import get_session, session_factory
    from app.main import app
    from app.queue import InlineDispatcher, set_dispatcher

    def no_teardown_commit() -> Iterator[Session]:
        session = session_factory()()
        try:
            yield session
            # Deliberately no commit: whatever survives, survives because
            # the endpoint committed it itself.
            session.rollback()
        finally:
            session.close()

    app.dependency_overrides[get_session] = no_teardown_commit
    set_dispatcher(InlineDispatcher())
    with TestClient(app) as test_client:
        yield test_client
    set_dispatcher(None)
    app.dependency_overrides.pop(get_session, None)


def _rows(model) -> int:
    from sqlalchemy import func, select

    from app.db import session_factory

    with session_factory()() as session:
        return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def test_an_upload_exists_the_moment_its_id_is_handed_out(client_without_teardown_commit, auth):
    from app.models import Upload

    response = client_without_teardown_commit.post(
        "/v1/uploads",
        json={"content_type": "image/png", "content_length": 1024},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert _rows(Upload) == 1, "the caller has an upload_id for a row that does not exist"


def test_a_batch_exists_the_moment_its_slots_are_handed_out(
    client_without_teardown_commit, auth, user, session
):
    from app.models import Batch, Upload

    user.plan = "pro"
    session.commit()

    response = client_without_teardown_commit.post(
        "/v1/batch",
        json={"count": 3, "content_type": "image/png", "content_length": 512},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert _rows(Batch) == 1
    assert _rows(Upload) == 3, "the caller has put_urls for uploads that do not exist"


def test_an_api_key_works_as_soon_as_it_is_returned(client_without_teardown_commit, auth):
    created = client_without_teardown_commit.post(
        "/v1/account/keys", json={"label": "ci"}, headers=auth
    )
    assert created.status_code == 201, created.text

    key = created.json()["key"]
    used = client_without_teardown_commit.get(
        "/v1/account", headers={"Authorization": f"Bearer {key}"}
    )
    assert used.status_code == 200, "a key that was just issued did not authenticate"


def test_revoking_a_key_takes_effect_when_the_caller_is_told_it_has(
    client_without_teardown_commit, auth
):
    created = client_without_teardown_commit.post(
        "/v1/account/keys", json={"label": "ci"}, headers=auth
    ).json()
    key_header = {"Authorization": f"Bearer {created['key']}"}
    assert client_without_teardown_commit.get("/v1/account", headers=key_header).status_code == 200

    revoked = client_without_teardown_commit.delete(
        f"/v1/account/keys/{created['id']}", headers=auth
    )
    assert revoked.status_code == 204

    after = client_without_teardown_commit.get("/v1/account", headers=key_header)
    assert after.status_code == 401, "a revoked key still worked"

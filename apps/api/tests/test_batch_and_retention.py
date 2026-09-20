"""§4.2 batches, §8 retention, §4.1 the delivery cap."""

from __future__ import annotations

import pytest

from app import credits


@pytest.fixture()
def pro_user(session, user):
    user.plan = "pro"
    credits.grant(session, user.id, source="pack", amount=50)
    session.commit()
    return user


def _run_batch(client, auth, images: list[bytes], options=None):
    created = client.post(
        "/v1/batch",
        json={
            "count": len(images),
            "options": options or {},
            "content_length": max(len(i) for i in images),
        },
        headers=auth,
    )
    assert created.status_code == 200, created.text
    batch = created.json()
    for slot, data in zip(batch["slots"], images, strict=True):
        client.put(slot["put_url"], content=data, headers={"Content-Type": "image/png"})
    started = client.post(
        f"/v1/batch/{batch['batch_id']}/start",
        json={"upload_ids": [s["upload_id"] for s in batch["slots"]]},
        headers=auth,
    )
    assert started.status_code == 200, started.text
    return batch["batch_id"], started.json()


def test_batch_runs_every_file_as_its_own_job(client, auth, pro_user, logo_png):
    batch_id, result = _run_batch(client, auth, [logo_png, logo_png, logo_png])
    assert result["total"] == 3
    assert result["completed"] == 3
    assert len(result["files"]) == 3

    from app.db import session_factory
    from app.models import Job

    with session_factory()() as s:
        jobs = s.query(Job).filter(Job.batch_id == batch_id).all()
        assert len(jobs) == 3, "a batch must be many jobs, never one"
        assert all(j.kind == "batch" for j in jobs)


def test_batch_zip_is_produced_and_downloadable(client, auth, pro_user, logo_png):
    batch_id, _ = _run_batch(client, auth, [logo_png, logo_png])
    status = client.get(f"/v1/batch/{batch_id}", headers=auth).json()
    assert status["status"] == "complete"
    assert status["zip_url"]

    import io
    import zipfile

    blob = client.get(status["zip_url"])
    assert blob.status_code == 200
    with zipfile.ZipFile(io.BytesIO(blob.content)) as archive:
        assert len(archive.namelist()) == 2


def test_batch_size_is_capped_by_plan(client, auth, user, session):
    user.plan = "free"
    session.commit()
    response = client.post("/v1/batch", json={"count": 25}, headers=auth)
    assert response.status_code == 403
    assert "plan allows" in response.json()["detail"]


def test_batch_count_over_500_is_rejected(client, auth, pro_user):
    assert client.post("/v1/batch", json={"count": 501}, headers=auth).status_code == 422


def test_failed_file_can_be_retried_individually(client, auth, pro_user, logo_png):
    batch_id, result = _run_batch(client, auth, [logo_png, b"not an image at all"])
    assert result["failed"] == 1
    failed = next(f for f in result["files"] if f["status"] == "failed")

    retried = client.post(
        f"/v1/batch/{batch_id}/retry/{failed['job_id']}", headers=auth
    )
    assert retried.status_code == 200
    # Still bad input, so it fails again — but the retry path works and only
    # that one file was re-run.
    assert retried.json()["total"] == 2


def test_partial_upload_does_not_fail_the_whole_batch(client, auth, pro_user, logo_png):
    created = client.post(
        "/v1/batch", json={"count": 3, "content_length": len(logo_png)}, headers=auth
    ).json()
    # Fill only two of the three slots.
    for slot in created["slots"][:2]:
        client.put(slot["put_url"], content=logo_png, headers={"Content-Type": "image/png"})
    started = client.post(
        f"/v1/batch/{created['batch_id']}/start",
        json={"upload_ids": [s["upload_id"] for s in created["slots"]]},
        headers=auth,
    )
    assert started.status_code == 200
    assert started.json()["total"] == 2


def test_retention_sweeper_purges_expired_jobs(client, auth, pro_user, logo_png, session):
    from datetime import timedelta

    from app.models import Job, utcnow
    from app.retention import sweep
    from tests.conftest import upload_and_vectorize

    body = upload_and_vectorize(client, auth, logo_png).json()
    client.post(f"/v1/jobs/{body['id']}/unlock", headers=auth)

    from app.db import session_factory

    with session_factory()() as s:
        job = s.get(Job, body["id"])
        job.expires_at = utcnow() - timedelta(hours=1)
        s.commit()

    with session_factory()() as s:
        assert sweep(s) >= 1
        s.commit()

    with session_factory()() as s:
        job = s.get(Job, body["id"])
        assert job.source_key is None
        assert job.output_keys == {}
        # The statistics survive; they contain no pixels (§5).
        assert job.profile is not None


def test_free_and_paid_work_land_under_separate_prefixes(
    client, auth, user, logo_png, session
):
    """R2 lifecycle rules key on these prefixes and are the retention backstop."""
    from tests.conftest import upload_and_vectorize

    user.plan = "free"
    session.commit()
    free_job = upload_and_vectorize(client, auth, logo_png).json()

    from app.db import session_factory
    from app.models import Job, User

    with session_factory()() as s:
        assert s.get(Job, free_job["id"]).source_key.startswith("free/")
        s.get(User, user.id).plan = "pro"
        s.commit()

    paid_job = upload_and_vectorize(client, auth, logo_png).json()
    with session_factory()() as s:
        assert s.get(Job, paid_job["id"]).source_key.startswith("paid/")


def test_delivery_cap_stops_a_poison_pill(tmp_env, monkeypatch, logo_png):
    """Late acks + requeue-on-loss would otherwise redeliver forever (§4.1)."""
    from celery.exceptions import Reject
    from worker import tasks

    from app.db import session_factory
    from app.models import Job, User

    with session_factory()() as s:
        s.add(User(id="usr_pill", email="pill@example.com"))
        s.flush()
        job = Job(
            id="job_pill", user_id="usr_pill", kind="sync", root_job_id="job_pill",
            status="queued", options={}, source_key="free/source/x/source.bin",
        )
        s.add(job)
        s.commit()

    deliveries = iter([1, 2, 3, 4])
    monkeypatch.setattr(tasks, "_deliveries", lambda _job_id: next(deliveries))

    # The first three deliveries attempt the job; the fourth is rejected
    # without requeue and the job is marked failed.
    for _ in range(3):
        tasks.vectorize_job.run("job_pill")

    with pytest.raises(Reject):
        tasks.vectorize_job.run("job_pill")

    with session_factory()() as s:
        job = s.get(Job, "job_pill")
        assert job.status == "failed"
        assert job.error_code in ("tracer_crash", "source_deleted")
        assert job.credits_charged == 0

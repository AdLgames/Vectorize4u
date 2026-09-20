"""§8's cost guardrail.

"Alert to Slack/email when daily compute cost deviates >15% from the
trailing 7-day moving average. An 8-candidate search's failure mode is a
large CPU bill."

The hard part of an alert is not firing it. It is not firing it on a quiet
Sunday, on the first day after a quiet week, or on a partial day — because
an alert that cries wolf is an alert nobody reads.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import costs


@pytest.fixture()
def usage(session, user):
    """Write a compute history, most recent day first."""

    def write(*per_day_ms: int, day: date | None = None) -> date:
        from app.models import UsageDaily

        today = day or date(2026, 6, 15)
        for offset, value in enumerate(per_day_ms):
            session.add(
                UsageDaily(
                    user_id=user.id,
                    date=today - timedelta(days=offset),
                    jobs=1,
                    compute_ms=value,
                )
            )
        session.commit()
        return today

    return write


def test_a_normal_day_says_nothing(session, usage):
    day = usage(100_000, 98_000, 102_000, 101_000, 99_000, 100_000, 97_000, 103_000)
    report = costs.report(session, day)
    assert report.alerting is False
    assert abs(report.deviation) < 0.05


def test_a_day_that_costs_double_is_an_alert(session, usage):
    day = usage(220_000, 100_000, 102_000, 98_000, 101_000, 99_000, 100_000)
    report = costs.report(session, day)
    assert report.alerting is True
    assert report.deviation > 1.0
    assert "above" in report.message()
    assert "120%" in report.message()


def test_a_collapse_is_also_an_alert(session, usage):
    """Compute falling off a cliff is a worker that stopped, which is worth
    knowing about just as fast as a bill that doubled."""
    day = usage(10_000, 100_000, 102_000, 98_000, 101_000, 99_000, 100_000)
    report = costs.report(session, day)
    assert report.alerting is True
    assert "below" in report.message()


def test_the_first_busy_day_after_a_quiet_week_is_not_an_alert(session, usage):
    """Days with no work are not evidence. Averaging zeros in would make
    every Monday morning an incident."""
    day = usage(500_000, 0, 0, 0, 0, 0, 0, 0)
    report = costs.report(session, day)
    assert report.alerting is False
    assert report.reason == "not enough history"


def test_tiny_numbers_do_not_produce_percentages(session, usage):
    """Two jobs against a baseline of one is a 100% deviation and nothing
    else. Below the floor, the check stays quiet."""
    day = usage(2_000, 1_000, 900, 1_100, 1_000)
    report = costs.report(session, day)
    assert report.alerting is False
    assert report.reason == "below the noise floor"


def test_the_message_says_what_changed(session, usage):
    day = usage(200_000, 100_000, 100_000, 100_000, 100_000)
    message = costs.report(session, day).message()
    assert "200s" in message
    assert "100s" in message
    assert day.isoformat() in message


def test_nothing_is_sent_when_no_webhook_is_configured(monkeypatch):
    """And it must not raise: an alerting path that can take the worker
    down with it is worse than no alerting path."""
    import httpx

    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("posted without a configured URL")

    monkeypatch.setattr(httpx, "post", explode)
    assert costs.notify("anything") is False


def test_a_configured_webhook_gets_slack_shaped_json(monkeypatch, tmp_env):
    import httpx

    from app.config import settings

    sent: dict = {}

    def capture(url, **kwargs):
        sent["url"] = url
        sent["json"] = kwargs["json"]
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setenv("VEC_ALERT_WEBHOOK_URL", "https://hooks.example.com/abc")
    settings.cache_clear()
    monkeypatch.setattr(httpx, "post", capture)

    assert costs.notify("compute doubled") is True
    assert sent["url"] == "https://hooks.example.com/abc"
    assert sent["json"] == {"text": "compute doubled"}
    settings.cache_clear()


def test_a_delivery_failure_is_not_fatal(monkeypatch, tmp_env):
    import httpx

    from app.config import settings

    monkeypatch.setenv("VEC_ALERT_WEBHOOK_URL", "https://hooks.example.com/abc")
    settings.cache_clear()
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down"))
    )
    assert costs.notify("compute doubled") is False
    settings.cache_clear()


def test_compute_time_is_recorded_when_a_job_completes(client, auth, logo_png, session):
    """The whole check rests on this column being written, and it has to be
    written at completion — job rows are deleted on schedule (§8), so a
    cost history derived from them later would evaporate with them."""
    from app.models import UsageDaily
    from tests.conftest import upload_and_vectorize

    assert upload_and_vectorize(client, auth, logo_png).status_code == 200
    session.expire_all()

    row = session.query(UsageDaily).one()
    assert row.compute_ms > 0, "a completed job recorded no compute time"

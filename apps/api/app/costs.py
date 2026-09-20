"""§8: alert when a day's compute does not look like the week before it.

"An 8-candidate search's failure mode is a large CPU bill" — and the bill
arrives a month after the mistake. What arrives immediately, if anyone is
looking, is a day that costs noticeably more than the trailing average:
a runaway retry loop, a batch of pathological images, a preset change that
quietly doubled the candidate count.

The number this watches is `usage_daily.compute_ms`, which is tracer time
rolled up per user per day. It is written when a job completes rather than
derived from job rows later, because job rows are deleted on schedule (§8)
and a cost history that evaporates with them is not a history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import UsageDaily


@dataclass(frozen=True)
class CostReport:
    day: date
    compute_ms: int
    baseline_ms: float
    deviation: float
    days_of_history: int
    alerting: bool
    reason: str

    def message(self) -> str:
        direction = "above" if self.deviation >= 0 else "below"
        return (
            f"Compute on {self.day.isoformat()} was "
            f"{self.compute_ms / 1000:.0f}s, {abs(self.deviation) * 100:.0f}% "
            f"{direction} the {self.days_of_history}-day average of "
            f"{self.baseline_ms / 1000:.0f}s."
        )


def daily_compute(session: Session, day: date) -> int:
    total = session.execute(
        select(func.coalesce(func.sum(UsageDaily.compute_ms), 0)).where(UsageDaily.date == day)
    ).scalar_one()
    return int(total)


def report(session: Session, day: date | None = None) -> CostReport:
    cfg = settings()
    day = day or date.today()
    window = cfg.cost_alert_window_days

    history: list[int] = []
    for offset in range(1, window + 1):
        previous = day - timedelta(days=offset)
        history.append(daily_compute(session, previous))

    # Days with no work at all are not evidence of anything; averaging them
    # in would make the first busy day after a quiet week an alert.
    observed = [value for value in history if value > 0]
    today = daily_compute(session, day)

    if len(observed) < 3:
        return CostReport(day, today, 0.0, 0.0, len(observed), False, "not enough history")

    baseline = sum(observed) / len(observed)
    deviation = (today - baseline) / baseline if baseline else 0.0

    if today < cfg.cost_alert_floor_ms and baseline < cfg.cost_alert_floor_ms:
        return CostReport(
            day, today, baseline, deviation, len(observed), False, "below the noise floor"
        )

    alerting = abs(deviation) > cfg.cost_alert_deviation
    reason = "deviation outside the threshold" if alerting else "within the threshold"
    return CostReport(day, today, baseline, deviation, len(observed), alerting, reason)


def notify(message: str) -> bool:
    """Post to the configured webhook. Returns whether anything was sent.

    Slack-shaped (`{"text": ...}`) because that is what an incoming webhook
    takes, and Slack is what §8 names. With no URL configured this logs and
    returns False rather than failing: an alerting path that can take the
    worker down with it is worse than no alerting path.
    """
    import logging

    log = logging.getLogger("vectorize.costs")
    url = settings().alert_webhook_url
    if not url:
        log.warning("cost alert (no VEC_ALERT_WEBHOOK_URL configured): %s", message)
        return False

    import httpx

    try:
        response = httpx.post(url, json={"text": message}, timeout=10.0)
        response.raise_for_status()
    except Exception:
        log.exception("could not deliver the cost alert: %s", message)
        return False
    return True

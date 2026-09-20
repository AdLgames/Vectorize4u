"""Phase 6 — rate limits and the overage cap.

§8 states the reason for the cap plainly: "so nobody gets a surprise
$4,000 invoice". The failure it guards against is a customer's own retry
loop, which is by definition not something they are watching at the time —
so the cap is on by default, refuses work at the door rather than after
doing it, and can only be removed by a deliberate act.
"""

from __future__ import annotations

import dataclasses

import pytest

from app import credits
from app.catalog import OVERAGE_UNIT_CENTS, overage_cap_credits, plan_for
from app.models import UsageDaily
from tests.conftest import upload_and_vectorize


@pytest.fixture()
def api_user(session, user):
    user.plan = "api"
    session.commit()
    return user


@pytest.fixture()
def api_key(client, auth, api_user):
    created = client.post("/v1/account/keys", json={"label": "ci"}, headers=auth).json()
    return {"Authorization": f"Bearer {created['key']}"}


def _limit(monkeypatch, plan: str, per_minute: int) -> None:
    """Products are frozen dataclasses on purpose — prices are not mutable
    state — so a test tightens a limit by swapping the catalog entry."""
    from app.catalog import CATALOG

    monkeypatch.setitem(
        CATALOG, plan, dataclasses.replace(CATALOG[plan], rate_per_minute=per_minute)
    )


def _burn_the_cap(session, user_id: str) -> int:
    """Put the account where a runaway retry loop would put it: the whole
    cap handed out as overage *and spent*, so the balance is back at zero."""
    cap = overage_cap_credits("api")
    credits.grant(session, user_id, source=credits.OVERAGE_SOURCE, amount=cap)
    credits.spend(session, user_id, amount=cap, reason="api_job")
    session.commit()
    return cap


# --- rate limits --------------------------------------------------------


def test_every_plan_has_a_rate_limit(client):
    """Including free. An unmetered key is a way to spend our CPU budget
    by accident."""
    for plan in ("free", "starter", "pro", "api", "something-renamed"):
        assert plan_for(plan).rate_per_minute > 0


def test_a_key_is_rate_limited_by_plan(client, api_key, api_user, monkeypatch):
    _limit(monkeypatch, "api", 3)

    codes = [client.get("/v1/account", headers=api_key).status_code for _ in range(2)]
    assert codes == [200, 200]

    # The limit applies to the job endpoints, which is where the cost is.
    seen = []
    for _ in range(4):
        response = client.post("/v1/vectorize", json={"upload_id": "nope"}, headers=api_key)
        seen.append(response.status_code)
    assert 429 in seen


def test_a_429_says_when_to_come_back(client, api_key, api_user, monkeypatch):
    _limit(monkeypatch, "api", 1)
    for _ in range(3):
        response = client.post("/v1/vectorize", json={"upload_id": "x"}, headers=api_key)
        if response.status_code == 429:
            assert int(response.headers["Retry-After"]) >= 1
            assert response.headers["RateLimit-Limit"] == "1"
            assert response.headers["RateLimit-Remaining"] == "0"
            return
    pytest.fail("never hit the limit")


def test_browser_sessions_are_not_per_key_limited(client, auth, user, monkeypatch):
    """A person with several tabs open is not an attack; the interactive
    paths have their own human-shaped limits."""
    _limit(monkeypatch, "starter", 1)
    codes = [client.get("/v1/account", headers=auth).status_code for _ in range(5)]
    assert codes == [200] * 5


def test_one_key_being_noisy_does_not_starve_another(client, auth, api_user, monkeypatch):
    """Limits are keyed on the API key, so revoking the noisy one is a
    complete fix."""
    _limit(monkeypatch, "api", 2)
    first = client.post("/v1/account/keys", json={"label": "a"}, headers=auth).json()
    second = client.post("/v1/account/keys", json={"label": "b"}, headers=auth).json()

    noisy = {"Authorization": f"Bearer {first['key']}"}
    quiet = {"Authorization": f"Bearer {second['key']}"}

    for _ in range(5):
        client.post("/v1/vectorize", json={"upload_id": "x"}, headers=noisy)

    response = client.post("/v1/vectorize", json={"upload_id": "x"}, headers=quiet)
    assert response.status_code != 429


# --- the overage cap ----------------------------------------------------


def test_the_cap_is_three_times_the_plan_price(api_user):
    cap = overage_cap_credits("api")
    assert cap * OVERAGE_UNIT_CENTS == 2900 * 3  # $87.00


def test_only_the_api_plan_has_overage(session, user):
    for plan in ("free", "starter", "pro"):
        assert overage_cap_credits(plan) == 0


def test_an_api_job_runs_past_zero_and_is_billed(client, api_key, api_user, logo_png, session):
    """That is what a usage plan means: the work continues, and the
    overage is recorded to invoice later."""
    assert credits.balance(session, api_user.id) == 0

    response = upload_and_vectorize(client, api_key, logo_png)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "complete"
    assert body["credits_charged"] == 1

    session.expire_all()
    assert credits.overage_used(session, api_user.id) == 1
    # And the ledger still balances: overage is a grant, not a negative.
    assert credits.balance(session, api_user.id) == 0


def test_prepaid_credit_is_spent_before_overage(client, api_key, api_user, logo_png, session):
    """Otherwise a customer with an unspent pack is invoiced for usage they
    had already paid for."""
    credits.grant(session, api_user.id, source="pack", amount=5)
    session.commit()

    upload_and_vectorize(client, api_key, logo_png)
    session.expire_all()

    assert credits.balance(session, api_user.id) == 4
    assert credits.overage_used(session, api_user.id) == 0


def test_the_cap_refuses_work_before_doing_it(client, api_key, api_user, logo_png, session):
    """Charging happens on completion, so a cap checked only afterwards
    would let the CPU be spent and the result delivered first."""
    cap = _burn_the_cap(session, api_user.id)

    response = upload_and_vectorize(client, api_key, logo_png)
    assert response.status_code == 402
    problem = response.json()
    assert problem["error_code"] == "overage_cap_reached"
    assert problem["overage_cap"] == cap
    assert "$87.00" in problem["detail"]


def test_a_plan_without_overage_gets_a_plain_402(client, auth, user, logo_png, session):
    user.plan = "starter"
    session.commit()
    key = client.post("/v1/account/keys", json={}, headers=auth).json()
    api = {"Authorization": f"Bearer {key['key']}"}

    response = upload_and_vectorize(client, api, logo_png)
    assert response.status_code == 402
    assert response.json()["error_code"] == "insufficient_credits"


def test_opting_out_removes_the_cap(client, api_key, auth, api_user, logo_png, session):
    _burn_the_cap(session, api_user.id)

    assert upload_and_vectorize(client, api_key, logo_png).status_code == 402

    opted = client.post("/v1/account/overage-cap", json={"opt_out": True}, headers=auth)
    assert opted.status_code == 200
    assert opted.json()["overage"]["cap_opted_out"] is True

    assert upload_and_vectorize(client, api_key, logo_png).status_code == 200


def test_opting_out_is_never_the_default(client, auth, api_user):
    assert client.get("/v1/account", headers=auth).json()["overage"]["cap_opted_out"] is False


def test_a_plan_without_overage_cannot_opt_out(client, auth, user, session):
    user.plan = "starter"
    session.commit()
    response = client.post("/v1/account/overage-cap", json={"opt_out": True}, headers=auth)
    assert response.status_code == 409


def test_the_account_shows_what_the_overage_would_cost(client, auth, api_key, api_user, logo_png):
    upload_and_vectorize(client, api_key, logo_png)
    overage = client.get("/v1/account", headers=auth).json()["overage"]
    assert overage["allowed"] is True
    assert overage["used"] == 1
    assert overage["estimated_cents"] == OVERAGE_UNIT_CENTS
    assert overage["unit_cents"] == OVERAGE_UNIT_CENTS


# --- usage --------------------------------------------------------------


def test_usage_is_recorded_for_invoicing(client, api_key, api_user, logo_png, session):
    """usage_daily has to survive the job being deleted on schedule (§8),
    so it is written when the work completes rather than derived later."""
    upload_and_vectorize(client, api_key, logo_png)
    session.expire_all()

    row = session.query(UsageDaily).filter(UsageDaily.user_id == api_user.id).one()
    assert row.jobs == 1
    assert row.credits == 1
    assert row.bytes_in == len(logo_png)
    # Real output bytes, not the length of a storage key.
    assert row.bytes_out > 1000


def test_usage_accumulates_within_a_day(client, api_key, api_user, logo_png, session):
    upload_and_vectorize(client, api_key, logo_png)
    upload_and_vectorize(client, api_key, logo_png)
    session.expire_all()
    row = session.query(UsageDaily).filter(UsageDaily.user_id == api_user.id).one()
    assert row.jobs == 2


def test_a_failed_job_records_usage_but_no_credits(client, api_key, api_user, session):
    created = client.post(
        "/v1/uploads", json={"content_type": "image/png", "content_length": 12}, headers=api_key
    ).json()
    client.put(created["put_url"], content=b"not an image", headers={"Content-Type": "image/png"})
    response = client.post(
        "/v1/vectorize", json={"upload_id": created["upload_id"]}, headers=api_key
    )
    assert response.json()["credits_charged"] == 0
    session.expire_all()
    assert credits.overage_used(session, api_user.id) == 0


def test_overage_rebuilds_from_the_ledger(client, api_key, api_user, logo_png, session):
    """The invariant everything else rests on, with overage in play."""
    upload_and_vectorize(client, api_key, logo_png)
    session.expire_all()

    from app.models import CreditGrant

    before = {g.id: g.remaining for g in session.query(CreditGrant).all()}
    credits.rebuild_projections(session, api_user.id)
    after = {g.id: g.remaining for g in session.query(CreditGrant).all()}
    assert before == after

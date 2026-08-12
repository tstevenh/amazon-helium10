"""Writing to Amazon must be impossible until deliberately enabled.

The app manages a live ad account. A bug, a stray test, or a misconfigured
deploy must not be able to change a bid. The kill-switch is the last line of
defence and is therefore built before anything that could use it.
"""
import inspect

import pytest

from app.config import settings
from app.core import amazon_ads_write as w
from app.core.amazon_ads_write import AmazonWriteDisabled


def test_write_is_disabled_by_default():
    """A fresh environment must never be able to change a live ad account.

    This asserts the *declared default*, not the current runtime value. The
    original version read settings.amazon_write_enabled, so it failed on any
    machine where writes were legitimately switched on — including the real
    deployment. A test that goes red exactly when the feature is in use
    trains people to ignore it, which is worse than not having it.
    """
    from app.config import Settings

    field = Settings.model_fields["amazon_write_enabled"]
    assert field.default is False, (
        "the kill-switch default must stay False so an unconfigured "
        "environment cannot write to Amazon"
    )


def test_assert_write_enabled_raises_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "amazon_write_enabled", False)
    with pytest.raises(AmazonWriteDisabled):
        w.assert_write_enabled()


def test_assert_write_enabled_passes_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "amazon_write_enabled", True)
    w.assert_write_enabled()   # must not raise


def test_every_public_write_function_checks_the_switch():
    """A new write function that forgets the guard is the dangerous case.

    This inspects source rather than behaviour deliberately: a future author
    adding a fourth write function gets a failing test even if they never
    write a behavioural test for it.
    """
    src = inspect.getsource(w)
    for name in ("update_keyword_bid", "update_target_bid", "create_negative_keyword",
                 "update_campaign_state", "update_campaign_budget"):
        if f"def {name}(" not in src:
            continue   # not implemented yet — Task 2 adds these
        fn_src = src[src.index(f"def {name}("):]
        guard = fn_src.find("assert_write_enabled()")
        for verb in ("_request_with_retry", "requests.put", "requests.post"):
            hit = fn_src.find(verb)
            if hit != -1:
                assert guard != -1 and guard < hit, (
                    f"{name} must call assert_write_enabled() before {verb}"
                )


def test_module_documents_why_the_switch_exists():
    """The safety model must be explained where the next author will read it."""
    assert w.__doc__ and "kill-switch" in w.__doc__.lower()


def test_campaign_state_cannot_archive():
    """Amazon cannot un-archive a campaign, so the app must never send it.

    A bad bid costs cents and is reversible. An archived campaign is gone —
    it cannot be restored through any API, only recreated by hand.
    """
    from app.core.amazon_ads_write import (
        CampaignStateRefused, _ALLOWED_CAMPAIGN_STATES, update_campaign_state,
    )

    assert "ARCHIVED" not in _ALLOWED_CAMPAIGN_STATES
    assert set(_ALLOWED_CAMPAIGN_STATES) == {"ENABLED", "PAUSED"}


def test_campaign_state_refuses_archive_before_checking_anything_else(monkeypatch):
    """The refusal must not depend on the kill-switch being on."""
    from app.core import amazon_ads_write as w
    from app.core.amazon_ads_write import AmazonWriteDisabled, CampaignStateRefused

    monkeypatch.setattr(settings, "amazon_write_enabled", True)
    with pytest.raises(CampaignStateRefused):
        w.update_campaign_state("tok", 1, 123, "ARCHIVED")


def test_campaign_state_is_still_gated_by_the_kill_switch(monkeypatch):
    from app.core import amazon_ads_write as w
    from app.core.amazon_ads_write import AmazonWriteDisabled

    monkeypatch.setattr(settings, "amazon_write_enabled", False)
    with pytest.raises(AmazonWriteDisabled):
        w.update_campaign_state("tok", 1, 123, "PAUSED")


def test_budget_write_is_gated_by_the_kill_switch(monkeypatch):
    from app.core import amazon_ads_write as w
    from app.core.amazon_ads_write import AmazonWriteDisabled

    monkeypatch.setattr(settings, "amazon_write_enabled", False)
    with pytest.raises(AmazonWriteDisabled):
        w.update_campaign_budget("tok", 1, 123, 10.0)


def test_budget_below_amazons_minimum_is_refused(monkeypatch):
    """Amazon's SP daily budget floor is $1.00.

    Catching it here turns a per-item API error into a clear local failure,
    and stops a rule from generating suggestions that can never execute.
    """
    from app.core import amazon_ads_write as w
    from app.core.amazon_ads_write import BudgetRefused

    monkeypatch.setattr(settings, "amazon_write_enabled", True)
    for bad in (0, 0.99, -5, None, "abc"):
        with pytest.raises(BudgetRefused):
            w.update_campaign_budget("tok", 1, 123, bad)


def test_budget_write_sends_only_the_budget():
    """It must not be able to pause a campaign or rename it."""
    import inspect

    body_lines = [
        line for line in inspect.getsource(w.update_campaign_budget).splitlines()
        if "body = " in line or '"campaignId"' in line or '"budget"' in line
    ]
    body_src = "\n".join(body_lines)
    for field in ('"state"', '"name"', '"targetingType"'):
        assert field not in body_src, f"budget write must not include {field}"

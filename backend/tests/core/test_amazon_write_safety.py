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
    for name in ("update_keyword_bid", "update_target_bid", "create_negative_keyword"):
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

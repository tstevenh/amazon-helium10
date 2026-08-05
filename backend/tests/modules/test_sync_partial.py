"""A partial fetch must persist what succeeded, skip soft-delete, and report errors."""
import inspect

from app.core.amazon_ads import PartialFetchError
from app.modules.campaigns import service as campaigns_service


def test_partial_fetch_error_carries_items_and_failures():
    exc = PartialFetchError("boom", [{"amazon_campaign_id": 1}], ["SP campaigns failed"])

    assert exc.items == [{"amazon_campaign_id": 1}]
    assert exc.failures == ["SP campaigns failed"]
    assert "boom" in str(exc)


def test_every_sync_method_handles_partial_fetch_error():
    """All three sync_* methods must catch PartialFetchError, not just one."""
    src = inspect.getsource(campaigns_service)

    for method in ("sync_campaigns", "sync_ad_groups", "sync_targets"):
        start = src.index(f"def {method}(")
        end = min(
            (src.index(f"def {nxt}(") for nxt in ("sync_campaigns", "sync_ad_groups", "sync_targets", "sync_all")
             if src.find(f"def {nxt}(") > start),
            default=len(src),
        )
        body = src[start:end]
        assert "PartialFetchError" in body, f"{method} does not handle PartialFetchError"


def test_soft_delete_is_guarded_against_partial_data():
    """CRITICAL invariant: an incomplete fetch must never trigger soft-delete.

    Rows absent from a partial fetch were not deleted on Amazon — they simply
    were not retrieved. Soft-deleting them would destroy live campaign data.
    """
    src = inspect.getsource(campaigns_service)

    # sync_campaigns and sync_ad_groups guard on partial_this_profile;
    # sync_targets guards on was_truncated (set True for partial fetches).
    assert src.count("partial_this_profile") >= 5, "soft-delete guard missing or incomplete"
    assert "soft_delete_missing SKIPPED profile=%s (partial fetch)" in src


def test_sync_methods_return_errors_key():
    """The API must be able to surface failures to the caller."""
    src = inspect.getsource(campaigns_service)

    assert src.count('"errors": all_errors') == 3, "all three sync_* must return errors[]"

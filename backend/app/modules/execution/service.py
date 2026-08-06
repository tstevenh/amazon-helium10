"""Suggestion execution — the only path from an approved suggestion to Amazon.

Ordering matters and is deliberate:

  1. Refuse unless the suggestion is 'approved'. A pending suggestion has not
     been reviewed by a human, and the spec is explicit: "Mandatory: Rule →
     Suggestion → Human Review → Apply. NO auto-apply in V1."
  2. Record the attempt BEFORE calling Amazon. If the process dies mid-call
     there must still be evidence that we tried, otherwise a change could
     exist on Amazon that we have no record of.
  3. Call Amazon — exactly one write per suggestion, per the spec.
  4. On success: write a change_log row (old → new) and mark executed.
  5. On failure: mark execution_failed and write NO change_log row. A
     change_log row means "this really changed on Amazon"; recording one for
     a failed call would make rollback restore a value that was never set.
"""
import logging
import uuid
from datetime import datetime, timezone as tz
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core import amazon_ads_write
from app.core.amazon_ads_write import AmazonWriteDisabled
from app.modules.accounts.models import AdsProfile, SellerAccount
from app.modules.accounts.service import AccountService
from app.modules.campaigns.models import AdGroup, Campaign, Target
from app.modules.execution.repository import (
    ACTION_EXECUTED,
    ACTION_EXECUTION_FAILED,
    ENTITY_TARGET,
    ExecutionRepository,
    SOURCE_SUGGESTION_EXECUTION,
)
from app.modules.suggestions.models import Suggestion

logger = logging.getLogger(__name__)

STATUS_APPROVED = "approved"
STATUS_EXECUTED = "executed"
STATUS_EXECUTION_FAILED = "execution_failed"

# Suggestion types this service knows how to apply. Anything else is refused
# rather than silently ignored — an unhandled type must not look executed.
_BID_TYPES = {"bid_increase", "bid_decrease", "bid_change"}
_NEGATIVE_TYPES = {"negative_exact", "negative_phrase"}


class ExecutionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ExecutionRepository(db)
        self._account_svc = AccountService(db)

    # ── helpers ───────────────────────────────────────────────────────────

    def _context(self, suggestion: Suggestion) -> tuple[AdsProfile, SellerAccount]:
        profile = (
            self.db.query(AdsProfile)
            .filter(AdsProfile.id == suggestion.profile_id)
            .one_or_none()
        )
        if profile is None:
            raise ValueError(f"Profile {suggestion.profile_id} not found")
        account = (
            self.db.query(SellerAccount)
            .filter(SellerAccount.id == profile.seller_account_id)
            .one_or_none()
        )
        if account is None:
            raise ValueError(f"Seller account for profile {profile.id} not found")
        return profile, account

    def _fail(
        self,
        suggestion: Suggestion,
        performed_by: uuid.UUID,
        detail: str,
        request: Optional[dict] = None,
        response: Optional[dict] = None,
        status_code: Optional[int] = None,
    ) -> dict[str, Any]:
        """Mark failed and record the attempt. Never writes a change_log row."""
        suggestion.status = STATUS_EXECUTION_FAILED
        self.db.commit()
        self.repo.record_attempt(
            suggestion.id, ACTION_EXECUTION_FAILED, performed_by=performed_by,
            request=request, response=response, status_code=status_code, notes=detail,
        )
        logger.error("[execution] suggestion %s FAILED: %s", suggestion.id, detail)
        return {"ok": False, "suggestion_id": str(suggestion.id),
                "status": STATUS_EXECUTION_FAILED, "detail": detail}

    # ── public API ────────────────────────────────────────────────────────

    def execute(self, suggestion_id: uuid.UUID, performed_by: uuid.UUID) -> dict[str, Any]:
        suggestion = (
            self.db.query(Suggestion).filter(Suggestion.id == suggestion_id).one_or_none()
        )
        if suggestion is None:
            return {"ok": False, "suggestion_id": str(suggestion_id),
                    "status": "not_found", "detail": "Suggestion not found"}

        # 1. Human review is mandatory — never execute a pending suggestion.
        if suggestion.status != STATUS_APPROVED:
            detail = (f"Suggestion is '{suggestion.status}', not '{STATUS_APPROVED}'. "
                      "Only approved suggestions may be executed.")
            logger.warning("[execution] refused %s: %s", suggestion_id, detail)
            return {"ok": False, "suggestion_id": str(suggestion_id),
                    "status": suggestion.status, "detail": detail}

        stype = (suggestion.suggestion_type or "").lower()
        if stype not in _BID_TYPES:
            # Negatives and product targets need their own execution paths;
            # refuse rather than pretend, so nothing is marked executed that
            # was never applied.
            return self._fail(
                suggestion, performed_by,
                f"Suggestion type '{stype}' is not executable yet. "
                f"Supported: {sorted(_BID_TYPES)}.",
            )

        target = (
            self.db.query(Target).filter(Target.id == suggestion.target_id).one_or_none()
            if suggestion.target_id else None
        )
        if target is None:
            return self._fail(suggestion, performed_by,
                              "Suggestion has no target_id — nothing to change.")

        new_bid = (suggestion.suggested_value or {}).get("bid")
        if new_bid is None:
            return self._fail(suggestion, performed_by,
                              "Suggestion has no suggested_value.bid — nothing to set.")

        # Read the old value from our synced copy. Recorded even if the write
        # fails, so there is always a record of what we believed it was.
        old_bid = (suggestion.current_value or {}).get("bid")
        if old_bid is None:
            old_bid = target.bid

        try:
            profile, account = self._context(suggestion)
        except ValueError as exc:
            return self._fail(suggestion, performed_by, str(exc))

        request_preview = {
            "keywords": [{"keywordId": str(target.amazon_target_id), "bid": float(new_bid)}]
        }

        # 2. Record BEFORE the call — evidence survives a crash mid-request.
        self.repo.record_attempt(
            suggestion.id, ACTION_EXECUTED, performed_by=performed_by,
            request=request_preview,
            notes=f"attempting bid {old_bid} -> {new_bid} on target "
                  f"{target.amazon_target_id}",
        )

        # 3. One suggestion, one Amazon call.
        try:
            token = self._account_svc.get_valid_access_token(account)
            result = amazon_ads_write.update_keyword_bid(
                token, profile.amazon_profile_id, target.amazon_target_id, float(new_bid)
            )
        except AmazonWriteDisabled as exc:
            return self._fail(suggestion, performed_by, str(exc), request=request_preview)
        except Exception as exc:
            return self._fail(suggestion, performed_by,
                              f"{type(exc).__name__}: {exc}", request=request_preview)

        if not result.get("ok"):
            # 5. Failure path — no change_log row, because nothing changed.
            return self._fail(
                suggestion, performed_by,
                "Amazon rejected the change",
                request=result.get("request"),
                response=result.get("response"),
                status_code=result.get("status_code"),
            )

        # 4. Success — record what really changed, then mark executed.
        self.repo.record_change(
            profile_id=profile.id,
            entity_type=ENTITY_TARGET,
            field_changed="bid",
            old_value=str(old_bid) if old_bid is not None else None,
            new_value=str(new_bid),
            source=SOURCE_SUGGESTION_EXECUTION,
            entity_id=target.id,
            amazon_entity_id=target.amazon_target_id,
            suggestion_id=suggestion.id,
            changed_by=performed_by,
        )
        self.repo.record_attempt(
            suggestion.id, ACTION_EXECUTED, performed_by=performed_by,
            request=result.get("request"), response=result.get("response"),
            status_code=result.get("status_code"), notes="confirmed by Amazon",
        )

        suggestion.status = STATUS_EXECUTED
        suggestion.executed_at = datetime.now(tz.utc)
        # Keep our local copy consistent until the next sync overwrites it.
        target.bid = new_bid
        self.db.commit()

        logger.warning("[execution] suggestion %s EXECUTED: target %s bid %s -> %s",
                       suggestion.id, target.amazon_target_id, old_bid, new_bid)
        return {"ok": True, "suggestion_id": str(suggestion.id),
                "status": STATUS_EXECUTED,
                "detail": f"bid {old_bid} -> {new_bid}"}

"""Performance sync service (Sprint 4B).

Orchestrates fetching Amazon reporting data and upserting to DB.
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core import amazon_reporting
from app.modules.accounts.models import AdsProfile, SellerAccount
from app.modules.accounts.repository import AdsProfileRepository, SellerAccountRepository
from app.modules.accounts.service import AccountService
from app.modules.campaigns.models import AdGroup, Campaign, Target
from app.modules.performance.repository import PerformanceRepository
from app.modules.performance.schemas import PerfSyncResult

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_DAYS = settings.amazon_perf_lookback_days
_RECENT_LOOKBACK_DAYS  = 3
# Max ad_group_ids per IN clause — avoids PostgreSQL statement_timeout on large
# profiles (e.g. profile 89389798686160 has 1 385 ad groups / 231 798 targets).
_TARGET_BATCH_SIZE = 200


class PerformanceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PerformanceRepository(db)
        self.profile_repo = AdsProfileRepository(db)
        self._account_svc = AccountService(db)

    def _get_access_token(self, account: SellerAccount, force: bool = False) -> str:
        return self._account_svc.get_valid_access_token(account, force_refresh=force)

    def _get_profiles(self, account: SellerAccount) -> list[AdsProfile]:
        profiles = self.profile_repo.get_by_account(account.id)
        if not profiles:
            raise ValueError(f"No profiles for account {account.id}")
        return profiles

    def _date_range(
        self,
        profile: AdsProfile,
        days: Optional[int] = None,
        force_full: bool = False,
    ) -> tuple[date, date]:
        end = date.today() - timedelta(days=1)
        if days:
            lookback = days
        elif force_full or not profile.last_perf_synced_at:
            lookback = _DEFAULT_LOOKBACK_DAYS
        else:
            lookback = _RECENT_LOOKBACK_DAYS
        start = end - timedelta(days=lookback - 1)
        return start, end

    def _campaign_id_map(self, profile_id: uuid.UUID) -> dict[int, Campaign]:
        rows = self.db.query(Campaign).filter(
            Campaign.profile_id == profile_id,
            Campaign.deleted_at.is_(None),
        ).all()
        return {c.amazon_campaign_id: c for c in rows}

    def _ad_group_id_map(self, profile_id: uuid.UUID) -> dict[int, AdGroup]:
        camp_ids = [c.id for c in self.db.query(Campaign).filter(
            Campaign.profile_id == profile_id, Campaign.deleted_at.is_(None)
        ).all()]
        if not camp_ids:
            return {}
        rows = self.db.query(AdGroup).filter(
            AdGroup.campaign_id.in_(camp_ids),
            AdGroup.deleted_at.is_(None),
        ).all()
        return {ag.amazon_ad_group_id: ag for ag in rows}

    def _target_key_map(self, profile_id: uuid.UUID) -> dict[tuple, Target]:
        """
        Returns a map keyed by (amazon_ad_group_id, match_type, expression_text_lower)
        for matching keyword targets from the reporting API.

        Batches the Target IN query in _TARGET_BATCH_SIZE chunks to avoid hitting
        PostgreSQL statement_timeout on large profiles (1 385 ad groups caused a
        QueryCanceled with the previous single-IN approach).
        """
        ag_map = self._ad_group_id_map(profile_id)
        if not ag_map:
            return {}

        # Reverse: AdGroup.id (UUID) -> amazon_ad_group_id (int)  — no extra DB call
        ag_uuid_to_amazon_id: dict = {ag.id: amazon_id for amazon_id, ag in ag_map.items()}

        ag_ids = list(ag_uuid_to_amazon_id.keys())
        rows: list[Target] = []
        for i in range(0, len(ag_ids), _TARGET_BATCH_SIZE):
            batch = ag_ids[i : i + _TARGET_BATCH_SIZE]
            batch_rows = self.db.query(Target).filter(
                Target.ad_group_id.in_(batch),
                Target.deleted_at.is_(None),
                Target.target_kind == "keyword",
            ).all()
            rows.extend(batch_rows)

        n_batches = max(1, (len(ag_ids) + _TARGET_BATCH_SIZE - 1) // _TARGET_BATCH_SIZE)
        logger.warning(
            "[perf] _target_key_map loaded %d keyword targets (%d ad groups, %d batches)",
            len(rows), len(ag_ids), n_batches,
        )

        result = {}
        for t in rows:
            amazon_ag_id = ag_uuid_to_amazon_id.get(t.ad_group_id)
            if amazon_ag_id is None:
                continue
            key = (
                amazon_ag_id,
                (t.match_type or "").lower(),
                (t.expression_text or "").lower(),
            )
            result[key] = t
        return result

    def sync_performance(
        self,
        account: SellerAccount,
        days: Optional[int] = None,
        force_full: bool = False,
    ) -> PerfSyncResult:
        access_token = self._get_access_token(account)
        profiles = self._get_profiles(account)

        total_camp = total_ag = total_tgt = 0
        start_date = end_date = None

        for profile in profiles:
            # Force-refresh token at the start of every profile.
            # Each profile can take 60-90 min to sync; the token from the
            # previous profile iteration will be expired by then.
            access_token = self._get_access_token(account, force=True)

            # token_getter is passed into each fetch_* call so the token is
            # also refreshed before every individual 31-day chunk inside
            # _fetch_report_chunked.  This prevents expiry mid-poll when a
            # single report takes ~20 min and there are 3+ chunks.
            token_getter: Callable[[], str] = lambda: self._get_access_token(account, force=True)

            start_date, end_date = self._date_range(profile, days, force_full=force_full)
            logger.warning("[perf] Syncing profile %s  %s -> %s (force_full=%s)",
                           profile.amazon_profile_id, start_date, end_date, force_full)

            # Skip profiles with no campaigns (avoids polling empty reports for 15+ min)
            camp_map = self._campaign_id_map(profile.id)
            if not camp_map:
                logger.warning("[perf] Skipping profile %s — no campaigns", profile.amazon_profile_id)
                profile.last_perf_synced_at = datetime.now(timezone.utc)
                self.db.commit()
                continue

            # ── Campaign performance ───────────────────────────────────────
            try:
                raw_camp = amazon_reporting.fetch_campaign_performance(
                    access_token, profile.amazon_profile_id, start_date, end_date,
                    token_getter=token_getter,
                )
                camp_rows = []
                for r in raw_camp:
                    camp = camp_map.get(r["amazon_campaign_id"])
                    if camp is None:
                        continue
                    camp_rows.append({
                        "campaign_id": str(camp.id), "date": r["date"],
                        "impressions": r["impressions"], "clicks": r["clicks"],
                        "spend": r["spend"], "sales": r["sales"], "orders": r["orders"],
                        "ctr": r["ctr"], "cpc": r["cpc"], "acos": r["acos"], "roas": r["roas"],
                    })
                total_camp += self.repo.upsert_campaign_perf(camp_rows)
                logger.warning("[perf] Campaign perf upserted %d rows (from %d raw)",
                               len(camp_rows), len(raw_camp))
            except Exception as exc:
                try:
                    self.db.rollback()
                except Exception:
                    pass
                logger.error("[perf] Campaign perf failed profile %s: %s", profile.amazon_profile_id, exc)

            # ── Ad group performance ───────────────────────────────────────
            try:
                # Force-refresh: campaign reports can take 30-60 min total across chunks
                access_token = self._get_access_token(account, force=True)
                ag_map = self._ad_group_id_map(profile.id)
                raw_ag = amazon_reporting.fetch_ad_group_performance(
                    access_token, profile.amazon_profile_id, start_date, end_date,
                    token_getter=token_getter,
                )
                ag_rows = []
                for r in raw_ag:
                    ag = ag_map.get(r["amazon_ad_group_id"])
                    if ag is None:
                        continue
                    ag_rows.append({
                        "ad_group_id": str(ag.id), "date": r["date"],
                        "impressions": r["impressions"], "clicks": r["clicks"],
                        "spend": r["spend"], "sales": r["sales"], "orders": r["orders"],
                        "ctr": r["ctr"], "cpc": r["cpc"], "acos": r["acos"], "roas": r["roas"],
                    })
                total_ag += self.repo.upsert_ad_group_perf(ag_rows)
                logger.warning("[perf] Ad group perf upserted %d rows (from %d raw)",
                               len(ag_rows), len(raw_ag))
            except Exception as exc:
                try:
                    self.db.rollback()
                except Exception:
                    pass
                logger.error("[perf] Ad group perf failed profile %s: %s", profile.amazon_profile_id, exc)

            # ── Target (keyword) performance ───────────────────────────────
            try:
                # Force-refresh: ad group reports can take another 30-60 min
                access_token = self._get_access_token(account, force=True)
                tgt_key_map = self._target_key_map(profile.id)
                raw_tgt = amazon_reporting.fetch_target_performance(
                    access_token, profile.amazon_profile_id, start_date, end_date,
                    token_getter=token_getter,
                )
                tgt_rows = []
                for r in raw_tgt:
                    key = (
                        r.get("amazon_ad_group_id"),
                        r.get("match_type", ""),
                        r.get("keyword_text", ""),
                    )
                    tgt = tgt_key_map.get(key)
                    if tgt is None:
                        continue
                    tgt_rows.append({
                        "target_id": str(tgt.id), "date": r["date"],
                        "impressions": r["impressions"], "clicks": r["clicks"],
                        "spend": r["spend"], "sales": r["sales"], "orders": r["orders"],
                        "ctr": r["ctr"], "cpc": r["cpc"], "acos": r["acos"], "roas": r["roas"],
                    })
                total_tgt += self.repo.upsert_target_perf(tgt_rows)
                logger.warning("[perf] Target perf upserted %d rows (from %d raw, map_size=%d)",
                               len(tgt_rows), len(raw_tgt), len(tgt_key_map))
            except Exception as exc:
                try:
                    self.db.rollback()
                except Exception:
                    pass
                logger.error("[perf] Target perf failed profile %s: %s", profile.amazon_profile_id, exc)

            # Mark profile synced — all errors above are rolled back so the
            # session is clean and this commit will always succeed.
            profile.last_perf_synced_at = datetime.now(timezone.utc)
            self.db.commit()

        logger.warning("[perf] sync_performance DONE camp=%d ag=%d tgt=%d profiles=%d",
                       total_camp, total_ag, total_tgt, len(profiles))
        return PerfSyncResult(
            campaign_rows=total_camp,
            ad_group_rows=total_ag,
            target_rows=total_tgt,
            date_from=start_date,
            date_to=end_date,
            profiles_synced=len(profiles),
        )

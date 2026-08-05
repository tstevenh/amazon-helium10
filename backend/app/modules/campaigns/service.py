"""
Campaign sync service — Sprint 1C / Sprint 4 defensive hardening + debug instrumentation.
Sprint 5: Profile fetches parallelised with ThreadPoolExecutor so all 3 profiles
          hit the Amazon API simultaneously. DB writes stay sequential (single session).
          This cuts per-endpoint wall time from ~60 s to ~20 s, staying under the
          Next.js dev proxy timeout.
Sprint 4B (bulk upsert): sync_campaigns / sync_ad_groups / sync_targets now call
          upsert_bulk() — one SQL statement per profile instead of N individual
          SELECT+INSERT/UPDATE+COMMIT round-trips.  1422 ad groups: ~2 s vs ~150 s.
"""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import amazon_ads
from app.core.amazon_ads import PartialFetchError
from app.modules.accounts.models import AdsProfile, SellerAccount
from app.modules.accounts.repository import AdsProfileRepository, CredentialRepository
from app.modules.accounts.service import AccountService
from app.modules.campaigns.models import AdGroup, Campaign
from app.modules.campaigns.repository import (
    AdGroupRepository,
    CampaignRepository,
    TargetRepository,
)

logger = logging.getLogger(__name__)

# Maximum number of profiles to fetch in parallel.
_PARALLEL_PROFILES = 5


class CampaignSyncService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.campaign_repo = CampaignRepository(db)
        self.ad_group_repo = AdGroupRepository(db)
        self.target_repo = TargetRepository(db)
        self.profile_repo = AdsProfileRepository(db)
        self._account_svc = AccountService(db)

    def _get_access_token(self, account: SellerAccount) -> str:
        return self._account_svc.get_valid_access_token(account)

    def _get_profiles(self, account: SellerAccount) -> list[AdsProfile]:
        profiles = self.profile_repo.get_by_account(account.id)
        if not profiles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Account {account.id} has no synced profiles. "
                    "Run /accounts/{id}/profiles/sync first."
                ),
            )
        return profiles

    # ── Campaign sync ─────────────────────────────────────────────────────

    def sync_campaigns(self, account: SellerAccount) -> dict:
        logger.warning("[svc] sync_campaigns starting for account %s", account.id)
        access_token = self._get_access_token(account)
        profiles = self._get_profiles(account)
        logger.warning("[svc] sync_campaigns: %d profiles (parallel fetch)", len(profiles))

        # ── Phase 1: fetch Amazon data for all profiles in parallel ────────
        def _fetch(profile: AdsProfile) -> tuple[AdsProfile, list[dict], Optional[Exception]]:
            try:
                raw = amazon_ads.list_campaigns(access_token, profile.amazon_profile_id)
                return profile, raw, None
            except PartialFetchError as exc:
                # Keep the rows that DID arrive — they are still worth persisting.
                return profile, exc.items, exc
            except Exception as exc:
                return profile, [], exc

        workers = min(len(profiles), _PARALLEL_PROFILES)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetch_results = list(ex.map(_fetch, profiles))

        # ── Phase 2: bulk-upsert to DB sequentially (single session) ──────
        total_upserted = 0
        total_deleted = 0
        total_skipped = 0
        total_pages = 0
        total_rows = 0
        any_truncated = False
        all_errors: list[str] = []

        for profile, raw_campaigns, fetch_error in fetch_results:
            # A PartialFetchError is recoverable: persist what arrived, record
            # the failure, and skip soft-delete for THIS profile only.
            partial_this_profile = False
            if isinstance(fetch_error, PartialFetchError):
                partial_this_profile = True
                all_errors.extend(fetch_error.failures)
                logger.error("[svc] sync_campaigns PARTIAL for profile %s: %s",
                             profile.amazon_profile_id, fetch_error)
            elif fetch_error is not None:
                logger.error("Campaign fetch failed for profile %s: %s",
                             profile.amazon_profile_id, fetch_error)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Amazon campaign sync failed for profile {profile.amazon_profile_id}: {fetch_error}",
                )

            logger.warning("[svc] sync_campaigns: profile %s returned %d campaigns",
                           profile.amazon_profile_id, len(raw_campaigns))

            try:
                count, seen_ids = self.campaign_repo.upsert_bulk(profile.id, raw_campaigns)
                total_upserted += count
            except SQLAlchemyError as exc:
                self.db.rollback()
                logger.error("Campaign bulk upsert failed for profile %s: %s",
                             profile.amazon_profile_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Campaign DB upsert failed for profile {profile.amazon_profile_id}: {exc}",
                )

            if partial_this_profile:
                # CRITICAL: an incomplete fetch is NOT evidence that the absent
                # rows are gone from Amazon — they simply were not retrieved.
                # Soft-deleting them here would destroy live campaign data.
                logger.warning(
                    "[svc] campaign soft_delete_missing SKIPPED profile=%s (partial fetch)",
                    profile.amazon_profile_id,
                )
            elif raw_campaigns:
                logger.warning("[svc] campaign soft_delete_missing profile=%s seen=%d",
                               profile.amazon_profile_id, len(seen_ids))
                deleted = self.campaign_repo.soft_delete_missing(profile.id, seen_ids)
                total_deleted += deleted
                logger.warning("[svc] campaign soft_delete_missing done profile=%s deleted=%d",
                               profile.amazon_profile_id, deleted)
            else:
                logger.warning("[svc] campaign soft_delete_missing SKIPPED profile=%s (Amazon returned empty)",
                               profile.amazon_profile_id)

        logger.warning("[svc] sync_campaigns done: upserted=%d deleted=%d skipped=%d errors=%d",
                       total_upserted, total_deleted, total_skipped, len(all_errors))
        return {
            "upserted": total_upserted,
            "soft_deleted": total_deleted,
            "errors": all_errors,
            "partial": bool(all_errors),
        }

    # ── Ad Group sync ─────────────────────────────────────────────────────

    def sync_ad_groups(self, account: SellerAccount) -> dict:
        logger.warning("[svc] sync_ad_groups starting for account %s", account.id)
        access_token = self._get_access_token(account)
        profiles = self._get_profiles(account)
        logger.warning("[svc] sync_ad_groups: %d profiles (parallel fetch)", len(profiles))

        # ── Phase 1: fetch Amazon data for all profiles in parallel ────────
        def _fetch(profile: AdsProfile) -> tuple[AdsProfile, list[dict], Optional[Exception]]:
            try:
                raw = amazon_ads.list_ad_groups(access_token, profile.amazon_profile_id)
                return profile, raw, None
            except PartialFetchError as exc:
                # Keep the rows that DID arrive — they are still worth persisting.
                return profile, exc.items, exc
            except Exception as exc:
                return profile, [], exc

        workers = min(len(profiles), _PARALLEL_PROFILES)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetch_results = list(ex.map(_fetch, profiles))

        # ── Phase 2: bulk-upsert to DB sequentially ───────────────────────
        total_upserted = 0
        total_deleted = 0
        total_skipped = 0
        total_pages = 0
        total_rows = 0
        any_truncated = False
        all_campaign_ids: list[uuid.UUID] = []
        all_errors: list[str] = []

        for profile, raw_ad_groups, fetch_error in fetch_results:
            partial_this_profile = False
            if isinstance(fetch_error, PartialFetchError):
                partial_this_profile = True
                all_errors.extend(fetch_error.failures)
                logger.error("[svc] sync_ad_groups PARTIAL for profile %s: %s",
                             profile.amazon_profile_id, fetch_error)
            elif fetch_error is not None:
                logger.error("Ad group fetch failed for profile %s: %s",
                             profile.amazon_profile_id, fetch_error)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Amazon ad group sync failed for profile {profile.amazon_profile_id}: {fetch_error}",
                )

            logger.warning("[svc] sync_ad_groups: profile %s returned %d ad_groups",
                           profile.amazon_profile_id, len(raw_ad_groups))

            # Load campaign FK map once per profile (fast single query).
            db_campaigns: dict[int, Campaign] = {
                c.amazon_campaign_id: c
                for c in self.campaign_repo.list_by_profile(profile.id, include_deleted=True)
            }

            # Resolve FKs and collect rows; skip any with unknown campaign.
            bulk_rows: list[dict] = []
            for raw in raw_ad_groups:
                amazon_campaign_id = int(raw["amazon_campaign_id"])
                db_campaign = db_campaigns.get(amazon_campaign_id)
                if db_campaign is None:
                    logger.warning(
                        "Ad group %s references unknown amazon_campaign_id %s — skipping",
                        raw.get("amazon_ad_group_id"), amazon_campaign_id,
                    )
                    total_skipped += 1
                    continue
                bulk_rows.append({
                    "campaign_id": db_campaign.id,
                    "amazon_ad_group_id": int(raw["amazon_ad_group_id"]),
                    "name": raw["name"],
                    "default_bid": raw.get("default_bid"),
                    "status": raw.get("status", "enabled"),
                })

            seen_ids = {r["amazon_ad_group_id"] for r in bulk_rows}

            try:
                count = self.ad_group_repo.upsert_bulk(bulk_rows)
                total_upserted += count
                logger.warning("[svc] sync_ad_groups: profile %s bulk upserted %d ad_groups",
                               profile.amazon_profile_id, count)
            except SQLAlchemyError as exc:
                self.db.rollback()
                logger.error("Ad group bulk upsert failed for profile %s: %s",
                             profile.amazon_profile_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Ad group DB upsert failed for profile {profile.amazon_profile_id}: {exc}",
                )

            campaign_ids = [c.id for c in db_campaigns.values()]
            all_campaign_ids.extend(campaign_ids)

            if partial_this_profile:
                # CRITICAL: incomplete fetch — absent rows were not retrieved,
                # not deleted on Amazon. Soft-deleting would destroy live data.
                logger.warning(
                    "[svc] ad_group soft_delete_missing SKIPPED profile=%s (partial fetch)",
                    profile.amazon_profile_id,
                )
            elif raw_ad_groups:
                logger.warning("[svc] ad_group soft_delete_missing profile=%s campaign_ids=%d seen=%d",
                               profile.amazon_profile_id, len(campaign_ids), len(seen_ids))
                deleted = self.ad_group_repo.soft_delete_missing(campaign_ids, seen_ids)
                total_deleted += deleted
                logger.warning("[svc] ad_group soft_delete_missing done profile=%s deleted=%d",
                               profile.amazon_profile_id, deleted)
            else:
                logger.warning("[svc] ad_group soft_delete_missing SKIPPED profile=%s (Amazon returned empty)",
                               profile.amazon_profile_id)

        logger.warning("[svc] sync_ad_groups done: upserted=%d deleted=%d skipped=%d errors=%d",
                       total_upserted, total_deleted, total_skipped, len(all_errors))
        return {
            "upserted": total_upserted,
            "soft_deleted": total_deleted,
            "errors": all_errors,
            "partial": bool(all_errors),
        }

    # ── Target sync ───────────────────────────────────────────────────────

    def sync_targets(self, account: SellerAccount) -> dict:
        logger.warning("[svc] sync_targets starting for account %s", account.id)
        access_token = self._get_access_token(account)
        profiles = self._get_profiles(account)
        logger.warning("[svc] sync_targets: %d profiles (parallel fetch)", len(profiles))

        # ── Phase 1: fetch Amazon data for all profiles in parallel ────────
        def _fetch(profile: AdsProfile) -> tuple[AdsProfile, list[dict], bool, int, int, Optional[Exception]]:
            try:
                raw, was_truncated, pages, rows = amazon_ads.list_targets(access_token, profile.amazon_profile_id)
                return profile, raw, was_truncated, pages, rows, None
            except PartialFetchError as exc:
                # Keep the rows that DID arrive. was_truncated=True marks the
                # view as incomplete so downstream soft-delete is skipped.
                return profile, exc.items, True, 0, len(exc.items), exc
            except Exception as exc:
                return profile, [], False, 0, 0, exc

        workers = min(len(profiles), _PARALLEL_PROFILES)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetch_results = list(ex.map(_fetch, profiles))

        # ── Phase 2: bulk-upsert to DB sequentially ───────────────────────
        total_upserted = 0
        total_deleted = 0
        total_skipped = 0
        total_pages = 0
        total_rows = 0
        any_truncated = False
        all_errors: list[str] = []

        for profile, raw_targets, was_truncated, pages, rows, fetch_error in fetch_results:
            partial_this_profile = False
            if isinstance(fetch_error, PartialFetchError):
                partial_this_profile = True
                all_errors.extend(fetch_error.failures)
                logger.error("[svc] sync_targets PARTIAL for profile %s: %s",
                             profile.amazon_profile_id, fetch_error)
            elif fetch_error is not None:
                logger.error("Target fetch failed for profile %s: %s",
                             profile.amazon_profile_id, fetch_error)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Amazon target sync failed for profile {profile.amazon_profile_id}: {fetch_error}",
                )

            logger.warning("[svc] sync_targets: profile %s returned %d targets pages=%d truncated=%s",
                           profile.amazon_profile_id, len(raw_targets), pages, was_truncated)
            total_pages += pages
            total_rows += rows
            if was_truncated:
                any_truncated = True

            profile_campaigns = self.campaign_repo.list_by_profile(profile.id, include_deleted=True)
            campaign_ids = [c.id for c in profile_campaigns]

            # Build ad_group FK map: amazon_ad_group_id → AdGroup
            db_ad_groups: dict[int, AdGroup] = {}
            for c in profile_campaigns:
                for ag in self.ad_group_repo.list_by_campaign(c.id, include_deleted=True):
                    db_ad_groups[ag.amazon_ad_group_id] = ag

            # Resolve FKs; skip any with unknown ad group.
            bulk_rows: list[dict] = []
            for raw in raw_targets:
                amazon_ad_group_id = int(raw["amazon_ad_group_id"])
                db_ad_group = db_ad_groups.get(amazon_ad_group_id)
                if db_ad_group is None:
                    logger.warning(
                        "Target %s references unknown amazon_ad_group_id %s — skipping",
                        raw.get("amazon_target_id"), amazon_ad_group_id,
                    )
                    total_skipped += 1
                    continue
                bulk_rows.append({
                    "ad_group_id": db_ad_group.id,
                    "amazon_target_id": int(raw["amazon_target_id"]),
                    "target_kind": raw["target_kind"],
                    "match_type": raw.get("match_type"),
                    "expression_text": raw.get("expression_text"),
                    "bid": raw.get("bid"),
                    "status": raw.get("status", "enabled"),
                })

            seen_ids = {r["amazon_target_id"] for r in bulk_rows}

            try:
                count = self.target_repo.upsert_bulk(bulk_rows)
                total_upserted += count
                logger.warning("[svc] sync_targets: profile %s bulk upserted %d targets",
                               profile.amazon_profile_id, count)
            except SQLAlchemyError as exc:
                self.db.rollback()
                logger.error("Target bulk upsert failed for profile %s: %s",
                             profile.amazon_profile_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Target DB upsert failed for profile {profile.amazon_profile_id}: {exc}",
                )

            ad_group_ids = [ag.id for ag in db_ad_groups.values()]

            if raw_targets and not was_truncated:
                # Full Amazon inventory returned — safe to soft_delete missing.
                logger.warning("[svc] target soft_delete_missing profile=%s ad_group_ids=%d seen=%d",
                               profile.amazon_profile_id, len(ad_group_ids), len(seen_ids))
                deleted = self.target_repo.soft_delete_missing(ad_group_ids, seen_ids)
                total_deleted += deleted
                logger.warning("[svc] target soft_delete_missing done profile=%s deleted=%d",
                               profile.amazon_profile_id, deleted)
            elif was_truncated:
                # Page cap was hit — only partial inventory fetched. Skipping
                # soft_delete to avoid incorrectly marking un-fetched targets as deleted.
                logger.warning(
                    "[svc] target soft_delete_missing SKIPPED profile=%s "
                    "(page cap active — fetched=%d, full inventory on Amazon is larger)",
                    profile.amazon_profile_id, len(raw_targets),
                )
            else:
                logger.warning("[svc] target soft_delete_missing SKIPPED profile=%s (Amazon returned empty)",
                               profile.amazon_profile_id)

        logger.warning("[svc] sync_targets done: upserted=%d deleted=%d skipped=%d pages=%d rows=%d truncated=%s errors=%d",
                       total_upserted, total_deleted, total_skipped, total_pages, total_rows,
                       any_truncated, len(all_errors))
        warnings = []
        if any_truncated:
            warnings.append(f"Full sync capped at {total_pages} pages ({total_rows} rows). Set AMAZON_FULL_SYNC_MAX_PAGES=0 for unlimited.")
        return {
            "upserted": total_upserted,
            "soft_deleted": total_deleted,
            "partial": any_truncated or bool(all_errors),
            "errors": all_errors,
            "warnings": warnings,
            "pages_fetched": total_pages,
            "rows_fetched": total_rows,
        }

    # ── Sync all ──────────────────────────────────────────────────────────

    def sync_all(self, account: SellerAccount) -> dict:
        logger.warning("[svc] sync_all starting for account %s", account.id)
        campaigns_result = self.sync_campaigns(account)
        logger.warning("[svc] sync_campaigns DONE: %s", campaigns_result)
        ad_groups_result = self.sync_ad_groups(account)
        logger.warning("[svc] sync_ad_groups DONE: %s", ad_groups_result)
        targets_result = self.sync_targets(account)
        logger.warning("[svc] sync_targets DONE: %s", targets_result)
        logger.warning("[svc] sync_all COMPLETE for account %s", account.id)
        return {
            "campaigns": campaigns_result,
            "ad_groups": ad_groups_result,
            "targets": targets_result,
        }

"""
Database access layer for campaigns, ad groups, and targets.

UPSERT pattern: insert on first sight, update all mutable fields on subsequent syncs.
Soft delete: set deleted_at for any amazon IDs that vanished from the API response.

Sprint 4 / Bulk perf: upsert_bulk() uses a single PostgreSQL INSERT ON CONFLICT DO UPDATE
statement per profile instead of N individual SELECT+INSERT/UPDATE+COMMIT round-trips.
This cuts ad_group sync from ~2.5 minutes (1422 × 100 ms) to under 2 seconds.
"""
import uuid
from datetime import datetime, timezone as tz
from decimal import Decimal
from typing import Optional

from sqlalchemy import null, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.campaigns.models import AdGroup, Campaign, Target

# Allowed status values per DB CHECK constraints.
_VALID_STATUSES = {"enabled", "paused", "archived"}


def _safe_status(s: Optional[str]) -> str:
    """Normalise Amazon status to a value accepted by the DB CHECK constraint."""
    s = (s or "enabled").lower()
    return s if s in _VALID_STATUSES else "enabled"


class CampaignRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(
        self,
        *,
        profile_id: uuid.UUID,
        amazon_campaign_id: int,
        ad_product: str,
        name: str,
        status: str,
        targeting_type: Optional[str],
        daily_budget: Optional[Decimal],
        start_date: Optional[str],
        end_date: Optional[str],
        bidding_strategy: Optional[str],
        raw_payload: Optional[dict],
    ) -> Campaign:
        from datetime import date as date_type
        now = datetime.now(tz.utc)

        def _parse_date(v: Optional[str]) -> Optional[date_type]:
            if not v:
                return None
            try:
                return date_type.fromisoformat(v)
            except ValueError:
                return None

        campaign = (
            self.db.query(Campaign)
            .filter(Campaign.amazon_campaign_id == amazon_campaign_id)
            .first()
        )
        if campaign is None:
            campaign = Campaign(
                profile_id=profile_id,
                amazon_campaign_id=amazon_campaign_id,
                ad_product=ad_product,
                name=name,
                status=status,
                targeting_type=targeting_type,
                daily_budget=daily_budget,
                start_date=_parse_date(start_date),
                end_date=_parse_date(end_date),
                bidding_strategy=bidding_strategy,
                raw_payload=raw_payload,
                last_synced_at=now,
                deleted_at=None,
            )
            self.db.add(campaign)
        else:
            campaign.profile_id = profile_id
            campaign.ad_product = ad_product
            campaign.name = name
            campaign.status = status
            campaign.targeting_type = targeting_type
            campaign.daily_budget = daily_budget
            campaign.start_date = _parse_date(start_date)
            campaign.end_date = _parse_date(end_date)
            campaign.bidding_strategy = bidding_strategy
            campaign.raw_payload = raw_payload
            campaign.last_synced_at = now
            campaign.deleted_at = None  # un-delete if it reappears
            campaign.updated_at = now

        self.db.commit()
        self.db.refresh(campaign)
        return campaign

    def upsert_bulk(
        self,
        profile_id: uuid.UUID,
        raws: list[dict],
    ) -> tuple[int, set[int]]:
        """
        Bulk-upsert campaigns from a list of normalised Amazon dicts.
        Returns (count_upserted, seen_amazon_ids).

        Uses a single PostgreSQL INSERT … ON CONFLICT DO UPDATE so the whole
        profile is written in one DB round-trip instead of N.
        """
        if not raws:
            return 0, set()

        from datetime import date as date_type
        now = datetime.now(tz.utc)

        def _parse_date(v: Optional[str]) -> Optional[date_type]:
            if not v:
                return None
            try:
                return date_type.fromisoformat(v)
            except ValueError:
                return None

        # Deduplicate by amazon_campaign_id (keep last); prevents PG error when
        # the same ID appears twice in one INSERT statement.
        deduped: dict[int, dict] = {}
        for r in raws:
            aid = int(r["amazon_campaign_id"])
            deduped[aid] = r

        values = [
            {
                "profile_id": profile_id,
                "amazon_campaign_id": aid,
                "ad_product": r.get("ad_product", "SP"),
                "name": r["name"],
                "status": _safe_status(r.get("status", "enabled")),
                "targeting_type": r.get("targeting_type"),
                "daily_budget": r.get("daily_budget"),
                "start_date": _parse_date(r.get("start_date")),
                "end_date": _parse_date(r.get("end_date")),
                "bidding_strategy": r.get("bidding_strategy"),
                "raw_payload": r,
                "last_synced_at": now,
                "deleted_at": None,
            }
            for aid, r in deduped.items()
        ]

        stmt = pg_insert(Campaign).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["amazon_campaign_id"],
            set_={
                "profile_id": stmt.excluded.profile_id,
                "ad_product": stmt.excluded.ad_product,
                "name": stmt.excluded.name,
                "status": stmt.excluded.status,
                "targeting_type": stmt.excluded.targeting_type,
                "daily_budget": stmt.excluded.daily_budget,
                "start_date": stmt.excluded.start_date,
                "end_date": stmt.excluded.end_date,
                "bidding_strategy": stmt.excluded.bidding_strategy,
                "raw_payload": stmt.excluded.raw_payload,
                "last_synced_at": stmt.excluded.last_synced_at,
                "deleted_at": null(),
                "updated_at": now,
            },
        )
        # Disable statement_timeout for this bulk operation so large accounts
        # don't hit PostgreSQL's default timeout during a sync.
        self.db.execute(text("SET LOCAL statement_timeout = 0"))
        self.db.execute(stmt)
        self.db.commit()

        seen_ids = set(deduped.keys())
        return len(values), seen_ids

    def soft_delete_missing(self, profile_id: uuid.UUID, seen_amazon_ids: set[int]) -> int:
        """Mark campaigns that weren't in the API response as deleted."""
        now = datetime.now(tz.utc)
        rows = (
            self.db.query(Campaign)
            .filter(
                Campaign.profile_id == profile_id,
                Campaign.deleted_at.is_(None),
                Campaign.amazon_campaign_id.notin_(seen_amazon_ids) if seen_amazon_ids
                else Campaign.amazon_campaign_id.isnot(None),
            )
            .all()
        )
        for c in rows:
            c.deleted_at = now
            c.updated_at = now
        self.db.commit()
        return len(rows)

    def get_by_id(self, campaign_id: uuid.UUID) -> Optional[Campaign]:
        return self.db.query(Campaign).filter(Campaign.id == campaign_id).first()

    def get_by_amazon_id(self, amazon_campaign_id: int) -> Optional[Campaign]:
        return (
            self.db.query(Campaign)
            .filter(Campaign.amazon_campaign_id == amazon_campaign_id)
            .first()
        )

    def list_by_profile(self, profile_id: uuid.UUID, include_deleted: bool = False) -> list[Campaign]:
        q = self.db.query(Campaign).filter(Campaign.profile_id == profile_id)
        if not include_deleted:
            q = q.filter(Campaign.deleted_at.is_(None))
        return q.order_by(Campaign.name).all()

    def list_all(self, include_deleted: bool = False) -> list[Campaign]:
        q = self.db.query(Campaign)
        if not include_deleted:
            q = q.filter(Campaign.deleted_at.is_(None))
        return q.order_by(Campaign.name).all()


class AdGroupRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(
        self,
        *,
        campaign_id: uuid.UUID,
        amazon_ad_group_id: int,
        name: str,
        default_bid: Optional[Decimal],
        status: str,
    ) -> AdGroup:
        now = datetime.now(tz.utc)
        ag = (
            self.db.query(AdGroup)
            .filter(AdGroup.amazon_ad_group_id == amazon_ad_group_id)
            .first()
        )
        if ag is None:
            ag = AdGroup(
                campaign_id=campaign_id,
                amazon_ad_group_id=amazon_ad_group_id,
                name=name,
                default_bid=default_bid,
                status=status,
                last_synced_at=now,
                deleted_at=None,
            )
            self.db.add(ag)
        else:
            ag.campaign_id = campaign_id
            ag.name = name
            ag.default_bid = default_bid
            ag.status = status
            ag.last_synced_at = now
            ag.deleted_at = None
            ag.updated_at = now

        self.db.commit()
        self.db.refresh(ag)
        return ag

    def upsert_bulk(self, rows: list[dict]) -> int:
        """
        Bulk-upsert ad groups.
        Each dict must have: campaign_id (UUID), amazon_ad_group_id (int),
        name (str), default_bid (Decimal|None), status (str).
        Returns the number of rows written.
        """
        if not rows:
            return 0

        now = datetime.now(tz.utc)

        # Deduplicate by amazon_ad_group_id
        deduped: dict[int, dict] = {}
        for r in rows:
            deduped[r["amazon_ad_group_id"]] = r

        values = [
            {
                "campaign_id": r["campaign_id"],
                "amazon_ad_group_id": aid,
                "name": r["name"],
                "default_bid": r.get("default_bid"),
                "status": _safe_status(r.get("status", "enabled")),
                "last_synced_at": now,
                "deleted_at": None,
            }
            for aid, r in deduped.items()
        ]

        stmt = pg_insert(AdGroup).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["amazon_ad_group_id"],
            set_={
                "campaign_id": stmt.excluded.campaign_id,
                "name": stmt.excluded.name,
                "default_bid": stmt.excluded.default_bid,
                "status": stmt.excluded.status,
                "last_synced_at": stmt.excluded.last_synced_at,
                "deleted_at": null(),
                "updated_at": now,
            },
        )
        # Disable statement_timeout for this bulk operation.
        self.db.execute(text("SET LOCAL statement_timeout = 0"))
        self.db.execute(stmt)
        self.db.commit()
        return len(values)

    def soft_delete_missing(self, campaign_ids: list[uuid.UUID], seen_amazon_ids: set[int]) -> int:
        """Mark ad groups that weren't in the API response as deleted."""
        now = datetime.now(tz.utc)
        if not campaign_ids:
            return 0
        rows = (
            self.db.query(AdGroup)
            .filter(
                AdGroup.campaign_id.in_(campaign_ids),
                AdGroup.deleted_at.is_(None),
                AdGroup.amazon_ad_group_id.notin_(seen_amazon_ids) if seen_amazon_ids
                else AdGroup.amazon_ad_group_id.isnot(None),
            )
            .all()
        )
        for ag in rows:
            ag.deleted_at = now
            ag.updated_at = now
        self.db.commit()
        return len(rows)

    def get_by_id(self, ad_group_id: uuid.UUID) -> Optional[AdGroup]:
        return self.db.query(AdGroup).filter(AdGroup.id == ad_group_id).first()

    def get_by_amazon_id(self, amazon_ad_group_id: int) -> Optional[AdGroup]:
        return (
            self.db.query(AdGroup)
            .filter(AdGroup.amazon_ad_group_id == amazon_ad_group_id)
            .first()
        )

    def list_by_campaign(self, campaign_id: uuid.UUID, include_deleted: bool = False) -> list[AdGroup]:
        q = self.db.query(AdGroup).filter(AdGroup.campaign_id == campaign_id)
        if not include_deleted:
            q = q.filter(AdGroup.deleted_at.is_(None))
        return q.order_by(AdGroup.name).all()

    def list_all(self, include_deleted: bool = False, profile_id: Optional[uuid.UUID] = None) -> list[AdGroup]:
        q = self.db.query(AdGroup)
        if profile_id is not None:
            q = q.join(Campaign, AdGroup.campaign_id == Campaign.id)
            q = q.filter(Campaign.profile_id == profile_id)
        if not include_deleted:
            q = q.filter(AdGroup.deleted_at.is_(None))
        return q.order_by(AdGroup.name).all()


class TargetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(
        self,
        *,
        ad_group_id: uuid.UUID,
        amazon_target_id: int,
        target_kind: str,
        match_type: Optional[str],
        expression_text: Optional[str],
        bid: Optional[Decimal],
        status: str,
    ) -> Target:
        now = datetime.now(tz.utc)
        target = (
            self.db.query(Target)
            .filter(Target.amazon_target_id == amazon_target_id)
            .first()
        )
        if target is None:
            target = Target(
                ad_group_id=ad_group_id,
                amazon_target_id=amazon_target_id,
                target_kind=target_kind,
                match_type=match_type,
                expression_text=expression_text,
                bid=bid,
                status=status,
                last_synced_at=now,
                deleted_at=None,
            )
            self.db.add(target)
        else:
            target.ad_group_id = ad_group_id
            target.target_kind = target_kind
            target.match_type = match_type
            target.expression_text = expression_text
            target.bid = bid
            target.status = status
            target.last_synced_at = now
            target.deleted_at = None
            target.updated_at = now

        self.db.commit()
        self.db.refresh(target)
        return target

    def upsert_bulk(self, rows: list[dict]) -> int:
        """
        Bulk-upsert targets.
        Each dict must have: ad_group_id (UUID), amazon_target_id (int),
        target_kind (str), match_type (str|None), expression_text (str|None),
        bid (Decimal|None), status (str).
        Processes in chunks of 500 to stay within psycopg2 parameter limits.
        Disables statement_timeout per chunk so large accounts don't time out.
        Returns total rows written.
        """
        if not rows:
            return 0

        _VALID_KINDS = {"keyword", "product", "audience"}
        _VALID_MATCH = {"exact", "phrase", "broad", "auto"}

        now = datetime.now(tz.utc)

        # Deduplicate by amazon_target_id
        deduped: dict[int, dict] = {}
        for r in rows:
            deduped[r["amazon_target_id"]] = r

        prepared = [
            {
                "ad_group_id": r["ad_group_id"],
                "amazon_target_id": aid,
                "target_kind": r["target_kind"] if r["target_kind"] in _VALID_KINDS else "keyword",
                "match_type": r.get("match_type") if r.get("match_type") in _VALID_MATCH else None,
                "expression_text": r.get("expression_text"),
                "bid": r.get("bid"),
                "status": _safe_status(r.get("status", "enabled")),
                "last_synced_at": now,
                "deleted_at": None,
            }
            for aid, r in deduped.items()
        ]

        CHUNK = 500
        total = 0
        for i in range(0, len(prepared), CHUNK):
            chunk = prepared[i : i + CHUNK]
            stmt = pg_insert(Target).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["amazon_target_id"],
                set_={
                    "ad_group_id": stmt.excluded.ad_group_id,
                    "target_kind": stmt.excluded.target_kind,
                    "match_type": stmt.excluded.match_type,
                    "expression_text": stmt.excluded.expression_text,
                    "bid": stmt.excluded.bid,
                    "status": stmt.excluded.status,
                    "last_synced_at": stmt.excluded.last_synced_at,
                    "deleted_at": null(),
                    "updated_at": now,
                },
            )
            # Disable statement_timeout for this chunk — large accounts (9k+ targets)
            # would otherwise hit PostgreSQL's default timeout.
            # SET LOCAL resets automatically when the transaction commits.
            self.db.execute(text("SET LOCAL statement_timeout = 0"))
            self.db.execute(stmt)
            self.db.commit()
            total += len(chunk)

        return total

    def soft_delete_missing(self, ad_group_ids: list[uuid.UUID], seen_amazon_ids: set[int]) -> int:
        now = datetime.now(tz.utc)
        if not ad_group_ids:
            return 0
        rows = (
            self.db.query(Target)
            .filter(
                Target.ad_group_id.in_(ad_group_ids),
                Target.deleted_at.is_(None),
                Target.amazon_target_id.notin_(seen_amazon_ids) if seen_amazon_ids
                else Target.amazon_target_id.isnot(None),
            )
            .all()
        )
        for t in rows:
            t.deleted_at = now
            t.updated_at = now
        self.db.commit()
        return len(rows)

    def get_by_id(self, target_id: uuid.UUID) -> Optional[Target]:
        return self.db.query(Target).filter(Target.id == target_id).first()

    def list_by_ad_group(self, ad_group_id: uuid.UUID, include_deleted: bool = False) -> list[Target]:
        q = self.db.query(Target).filter(Target.ad_group_id == ad_group_id)
        if not include_deleted:
            q = q.filter(Target.deleted_at.is_(None))
        return q.order_by(Target.target_kind, Target.expression_text).all()

    def list_all(
        self,
        target_kind: Optional[str] = None,
        ad_group_id: Optional[uuid.UUID] = None,
        profile_id: Optional[uuid.UUID] = None,
        limit: Optional[int] = None,
        include_deleted: bool = False,
    ) -> list[Target]:
        q = self.db.query(Target)
        if target_kind:
            q = q.filter(Target.target_kind == target_kind)
        if ad_group_id:
            q = q.filter(Target.ad_group_id == ad_group_id)
        if profile_id is not None:
            q = (q.join(AdGroup, Target.ad_group_id == AdGroup.id)
                  .join(Campaign, AdGroup.campaign_id == Campaign.id)
                  .filter(Campaign.profile_id == profile_id))
        if not include_deleted:
            q = q.filter(Target.deleted_at.is_(None))
        q = q.order_by(Target.expression_text)
        if limit is not None:
            q = q.limit(limit)
        return q.all()

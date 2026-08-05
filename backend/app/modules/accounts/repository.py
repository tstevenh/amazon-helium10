"""
Database access layer for accounts, credentials, and ads profiles.

All DB writes go through this module — no raw SQL or ORM writes in service.py.
"""
import uuid
from datetime import datetime, timezone as tz
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.accounts.models import AdsProfile, Credential, SellerAccount


class SellerAccountRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, name: str, created_by: uuid.UUID) -> SellerAccount:
        account = SellerAccount(name=name, created_by=created_by)
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def get_by_id(self, account_id: uuid.UUID) -> Optional[SellerAccount]:
        return (
            self.db.query(SellerAccount)
            .filter(SellerAccount.id == account_id)
            .first()
        )

    def list_all(self) -> list[SellerAccount]:
        return (
            self.db.query(SellerAccount)
            .order_by(SellerAccount.created_at.desc())
            .all()
        )


class CredentialRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_account(self, seller_account_id: uuid.UUID) -> Optional[Credential]:
        return (
            self.db.query(Credential)
            .filter(Credential.seller_account_id == seller_account_id)
            .first()
        )

    def upsert(
        self,
        *,
        seller_account_id: uuid.UUID,
        refresh_token_encrypted: str,
        access_token_encrypted: Optional[str],
        token_expires_at: Optional[datetime],
        created_by: uuid.UUID,
    ) -> Credential:
        cred = self.get_by_account(seller_account_id)
        if cred is None:
            cred = Credential(
                seller_account_id=seller_account_id,
                refresh_token_encrypted=refresh_token_encrypted,
                access_token_encrypted=access_token_encrypted,
                token_expires_at=token_expires_at,
                created_by=created_by,
            )
            self.db.add(cred)
        else:
            cred.refresh_token_encrypted = refresh_token_encrypted
            if access_token_encrypted is not None:
                cred.access_token_encrypted = access_token_encrypted
            if token_expires_at is not None:
                cred.token_expires_at = token_expires_at
            cred.updated_at = datetime.now(tz.utc)
        self.db.commit()
        self.db.refresh(cred)
        return cred

    def update_access_token(
        self,
        cred: Credential,
        *,
        access_token_encrypted: str,
        token_expires_at: datetime,
    ) -> Credential:
        cred.access_token_encrypted = access_token_encrypted
        cred.token_expires_at = token_expires_at
        cred.updated_at = datetime.now(tz.utc)
        self.db.commit()
        self.db.refresh(cred)
        return cred


class AdsProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_account(self, seller_account_id: uuid.UUID) -> list[AdsProfile]:
        return (
            self.db.query(AdsProfile)
            .filter(AdsProfile.seller_account_id == seller_account_id)
            .all()
        )

    def upsert(
        self,
        *,
        seller_account_id: uuid.UUID,
        amazon_profile_id: int,
        marketplace_code: str,
        country_code: Optional[str],
        currency_code: Optional[str],
        timezone_str: Optional[str],
    ) -> AdsProfile:
        """
        Insert or update a profile by amazon_profile_id.

        Parameter is named timezone_str (not timezone) to avoid shadowing
        datetime.timezone in this module's namespace.
        """
        now = datetime.now(tz.utc)
        profile = (
            self.db.query(AdsProfile)
            .filter(
                AdsProfile.amazon_profile_id == amazon_profile_id,
                AdsProfile.seller_account_id == seller_account_id,
            )
            .first()
        )
        if profile is None:
            profile = AdsProfile(
                seller_account_id=seller_account_id,
                amazon_profile_id=amazon_profile_id,
                marketplace_code=marketplace_code,
                country_code=country_code,
                currency_code=currency_code,
                timezone=timezone_str,
                status="active",
                last_synced_at=now,
            )
            self.db.add(profile)
        else:
            profile.marketplace_code = marketplace_code
            profile.country_code = country_code
            profile.currency_code = currency_code
            profile.timezone = timezone_str
            profile.status = "active"
            profile.last_synced_at = now
            profile.updated_at = now
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def find_duplicate_owner(
        self, amazon_profile_ids: list[int], exclude_account_id: uuid.UUID
    ) -> tuple[int, str] | None:
        """
        Check if any of the given amazon_profile_ids is already connected
        to a DIFFERENT seller account.

        Returns (amazon_profile_id, existing_account_name) if a duplicate is found,
        otherwise None.
        """
        if not amazon_profile_ids:
            return None
        from app.modules.accounts.models import SellerAccount as SA
        row = (
            self.db.query(AdsProfile.amazon_profile_id, SA.name)
            .join(SA, SA.id == AdsProfile.seller_account_id)
            .filter(
                AdsProfile.amazon_profile_id.in_(amazon_profile_ids),
                AdsProfile.seller_account_id != exclude_account_id,
            )
            .first()
        )
        if row:
            return (row[0], row[1])
        return None

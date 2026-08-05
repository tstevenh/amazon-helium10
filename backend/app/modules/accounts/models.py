"""
SQLAlchemy ORM models for Sprint 1B accounts, credentials, and ads profiles.

These models map exactly to the tables created in migration 002.
Do not alter column definitions here without a corresponding migration.
"""
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class SellerAccount(Base):
    __tablename__ = "seller_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String(255), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    credential = relationship(
        "Credential",
        back_populates="seller_account",
        uselist=False,
        cascade="all, delete-orphan",
    )
    profiles = relationship(
        "AdsProfile",
        back_populates="seller_account",
        cascade="all, delete-orphan",
    )


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    seller_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("seller_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    refresh_token_encrypted = Column(Text(), nullable=False)
    access_token_encrypted = Column(Text(), nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    seller_account = relationship("SellerAccount", back_populates="credential")


class AdsProfile(Base):
    __tablename__ = "ads_profiles"

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled', 'auth_required')",
            name="ck_ads_profiles_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    seller_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("seller_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    amazon_profile_id = Column(BigInteger(), nullable=False, unique=True)
    marketplace_code = Column(String(50), nullable=False)
    country_code = Column(String(5), nullable=True)
    currency_code = Column(String(5), nullable=True)
    timezone = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, server_default="active")
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_perf_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    seller_account = relationship("SellerAccount", back_populates="profiles")

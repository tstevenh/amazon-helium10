"""Sprint 4B — Ad Group performance table + perf sync tracking

Migration 004 already created campaign_performance_daily and
target_performance_daily. This migration adds:

  1. ad_group_performance_daily — SP ad-group-level daily metrics
     sourced from the spAdGroups Amazon Reporting API report.
     UPSERT key: (ad_group_id, date).

  2. last_perf_synced_at column on ads_profiles — tracks when
     performance data was last fetched for each profile so the
     frontend can show freshness and the sync endpoint can choose
     a sensible lookback window.

Revision ID: 011
Revises: 010
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. ad_group_performance_daily ─────────────────────────────────────
    op.create_table(
        "ad_group_performance_daily",
        sa.Column(
            "id", UUID(), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ad_group_id", UUID(),
            sa.ForeignKey("ad_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("spend", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("sales", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Numeric(10, 6), nullable=True),
        sa.Column("cpc", sa.Numeric(10, 4), nullable=True),
        sa.Column("acos", sa.Numeric(10, 4), nullable=True),
        sa.Column("roas", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ad_group_id", "date", name="uq_agpd_ad_group_date"),
    )
    op.create_index("idx_agpd_ad_group_date", "ad_group_performance_daily", ["ad_group_id", "date"])
    op.create_index("idx_agpd_date", "ad_group_performance_daily", ["date"])

    # ── 2. last_perf_synced_at on ads_profiles ────────────────────────────
    op.add_column(
        "ads_profiles",
        sa.Column("last_perf_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ads_profiles", "last_perf_synced_at")

    op.drop_index("idx_agpd_date", table_name="ad_group_performance_daily")
    op.drop_index("idx_agpd_ad_group_date", table_name="ad_group_performance_daily")
    op.drop_table("ad_group_performance_daily")

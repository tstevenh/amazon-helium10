"""003 create campaigns, ad_groups, targets

Revision ID: 003
Revises: 002
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amazon_campaign_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("ad_product", sa.String(5), nullable=False, server_default="SP"),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("targeting_type", sa.String(10), nullable=True),
        sa.Column("daily_budget", sa.Numeric(12, 2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("bidding_strategy", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("ad_product IN ('SP', 'SB', 'SD')", name="ck_campaigns_ad_product"),
        sa.CheckConstraint("status IN ('enabled', 'paused', 'archived')", name="ck_campaigns_status"),
        sa.CheckConstraint(
            "targeting_type IS NULL OR targeting_type IN ('manual', 'auto')",
            name="ck_campaigns_targeting_type",
        ),
    )
    op.create_index("idx_campaigns_profile_status", "campaigns", ["profile_id", "status"])

    op.create_table(
        "ad_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amazon_ad_group_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("default_bid", sa.Numeric(8, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('enabled', 'paused', 'archived')", name="ck_ad_groups_status"),
    )
    op.create_index("idx_ad_groups_campaign", "ad_groups", ["campaign_id"])

    op.create_table(
        "targets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ad_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ad_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amazon_target_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("target_kind", sa.String(10), nullable=False),
        sa.Column("match_type", sa.String(20), nullable=True),
        sa.Column("expression_text", sa.String(500), nullable=True),
        sa.Column("bid", sa.Numeric(8, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "target_kind IN ('keyword', 'product', 'audience')", name="ck_targets_target_kind"
        ),
        sa.CheckConstraint(
            "match_type IS NULL OR match_type IN ('exact', 'phrase', 'broad', 'auto')",
            name="ck_targets_match_type",
        ),
        sa.CheckConstraint("status IN ('enabled', 'paused', 'archived')", name="ck_targets_status"),
    )
    op.create_index("idx_targets_ad_group", "targets", ["ad_group_id"])
    op.create_index("idx_targets_expression_text", "targets", ["expression_text"])


def downgrade() -> None:
    op.drop_index("idx_targets_expression_text", table_name="targets")
    op.drop_index("idx_targets_ad_group", table_name="targets")
    op.drop_table("targets")

    op.drop_index("idx_ad_groups_campaign", table_name="ad_groups")
    op.drop_table("ad_groups")

    op.drop_index("idx_campaigns_profile_status", table_name="campaigns")
    op.drop_table("campaigns")

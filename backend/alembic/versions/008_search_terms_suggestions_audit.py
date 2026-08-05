"""Add search_terms, suggestions, audit_log tables

Revision ID: 008
Revises: 007
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── search_terms ──────────────────────────────────────────────────────
    op.create_table(
        "search_terms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", UUID(as_uuid=True),
                  sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ad_group_id", UUID(as_uuid=True),
                  sa.ForeignKey("ad_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("search_term", sa.String(500), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("sales", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("orders", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ctr", sa.Numeric(8, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("cpc", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("acos", sa.Numeric(8, 6), nullable=True),
        sa.Column("roas", sa.Numeric(10, 4), nullable=True),
        sa.Column("conversion_rate", sa.Numeric(8, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint(
        "uq_search_terms_profile_adgroup_term_date",
        "search_terms",
        ["profile_id", "ad_group_id", "search_term", "date"],
    )
    op.create_index("idx_st_profile_id", "search_terms", ["profile_id"])
    op.create_index("idx_st_campaign_id", "search_terms", ["campaign_id"])
    op.create_index("idx_st_date", "search_terms", ["date"])

    # ── suggestions ───────────────────────────────────────────────────────
    op.create_table(
        "suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", UUID(as_uuid=True),
                  sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ad_group_id", UUID(as_uuid=True),
                  sa.ForeignKey("ad_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("search_term", sa.String(500), nullable=False),
        sa.Column("suggestion_type", sa.String(50), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("metrics_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("resolved_by", UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_suggestions_profile_id", "suggestions", ["profile_id"])
    op.create_index("idx_suggestions_status", "suggestions", ["status"])
    op.create_index("idx_suggestions_kind", "suggestions", ["kind"])

    # ── audit_log ─────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_audit_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("idx_audit_user_id", "audit_log", ["user_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("suggestions")
    op.drop_table("search_terms")

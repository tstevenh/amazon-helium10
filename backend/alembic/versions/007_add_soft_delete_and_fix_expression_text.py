"""007 add soft delete columns to campaign tables and fix targets.expression_text

Changes
-------
1. campaigns.deleted_at       — nullable TIMESTAMPTZ, set when campaign disappears from Amazon
2. ad_groups.deleted_at       — nullable TIMESTAMPTZ, same
3. targets.deleted_at         — nullable TIMESTAMPTZ, same
4. targets.expression_text    — VARCHAR(500) → TEXT
   Reason: product targeting expressions (ASIN lists, category paths) can exceed 500 chars.
5. sync_jobs.job_type CHECK   — add 'ad_group_sync' and 'target_sync' to the allowed set

Soft-delete convention
----------------------
deleted_at IS NULL     → record is active
deleted_at IS NOT NULL → record was removed from Amazon API; kept for audit trail

Revision ID: 007
Revises: 006
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Soft-delete columns ───────────────────────────────────────────────
    op.add_column("campaigns", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ad_groups", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("targets", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # Partial indexes: fast lookup of active (non-deleted) rows
    op.create_index(
        "idx_campaigns_active",
        "campaigns",
        ["profile_id", "status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_ad_groups_active",
        "ad_groups",
        ["campaign_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_targets_active",
        "targets",
        ["ad_group_id", "target_kind"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── Widen targets.expression_text to TEXT ─────────────────────────────
    op.alter_column(
        "targets",
        "expression_text",
        type_=sa.Text(),
        existing_type=sa.String(500),
        existing_nullable=True,
    )

    # ── Extend sync_jobs.job_type CHECK constraint ────────────────────────
    op.drop_constraint("ck_sync_jobs_job_type", "sync_jobs", type_="check")
    op.create_check_constraint(
        "ck_sync_jobs_job_type",
        "sync_jobs",
        "job_type IN ('profile_sync', 'campaign_sync', 'ad_group_sync', 'target_sync', 'performance_sync')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sync_jobs_job_type", "sync_jobs", type_="check")
    op.create_check_constraint(
        "ck_sync_jobs_job_type",
        "sync_jobs",
        "job_type IN ('profile_sync', 'campaign_sync', 'performance_sync')",
    )

    op.alter_column(
        "targets",
        "expression_text",
        type_=sa.String(500),
        existing_type=sa.Text(),
        existing_nullable=True,
    )

    op.drop_index("idx_targets_active", table_name="targets")
    op.drop_index("idx_ad_groups_active", table_name="ad_groups")
    op.drop_index("idx_campaigns_active", table_name="campaigns")

    op.drop_column("targets", "deleted_at")
    op.drop_column("ad_groups", "deleted_at")
    op.drop_column("campaigns", "deleted_at")

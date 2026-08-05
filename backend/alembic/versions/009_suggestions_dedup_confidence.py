"""Sprint 2.5 — Suggestion deduplication + confidence score

Revision ID: 009
Revises: 008
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Add aggregation + confidence columns ──────────────────────────────
    op.add_column("suggestions", sa.Column(
        "confidence_score", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("suggestions", sa.Column(
        "campaign_count", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column("suggestions", sa.Column(
        "ad_group_count", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column("suggestions", sa.Column(
        "total_spend", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")))
    op.add_column("suggestions", sa.Column(
        "total_sales", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")))
    op.add_column("suggestions", sa.Column(
        "total_orders", sa.Integer(), nullable=False, server_default=sa.text("0")))

    # ── Deduplicate existing pending suggestions ────────────────────────────
    # Keep only the most-recently-created pending suggestion per
    # (profile_id, search_term, suggestion_type); delete older duplicates.
    op.execute(sa.text("""
        DELETE FROM suggestions
        WHERE status = 'pending'
          AND id NOT IN (
              SELECT DISTINCT ON (profile_id, search_term, suggestion_type) id
              FROM suggestions
              WHERE status = 'pending'
              ORDER BY profile_id, search_term, suggestion_type, created_at DESC
          )
    """))

    # ── Partial unique index: one pending suggestion per (profile, term, type) ──
    op.create_index(
        "uq_suggestion_pending_profile_term_type",
        "suggestions",
        ["profile_id", "search_term", "suggestion_type"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_suggestion_pending_profile_term_type", table_name="suggestions")
    op.drop_column("suggestions", "total_orders")
    op.drop_column("suggestions", "total_sales")
    op.drop_column("suggestions", "total_spend")
    op.drop_column("suggestions", "ad_group_count")
    op.drop_column("suggestions", "campaign_count")
    op.drop_column("suggestions", "confidence_score")

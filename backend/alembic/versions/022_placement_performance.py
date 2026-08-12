"""placement performance — spend by where the ad appeared

Spec §8: placement_performance_daily, fed by the Placement Report
(placementClassification). Verified available for this account on 2026-08-12:
groupBy ['campaign','campaignPlacement'] returns HTTP 200, unlike the hourly
report which Amazon refuses outright.

Placement matters because the same campaign performs very differently at the
top of search than on a product page, and Amazon lets you bid a multiplier per
placement rather than only per keyword.

Revision ID: 022
Revises: 021
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "placement_performance_daily",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        # Normalized from Amazon's placementClassification strings, which are
        # verbose and have changed spelling between API versions.
        sa.Column("placement", sa.String(30), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("spend", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("sales", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("orders", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Stored rather than derived so a row is self-describing in SQL, matching
        # the other *_performance_daily tables.
        sa.Column("acos", sa.Numeric(12, 4), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "placement IN ('top_of_search', 'product_pages', 'rest_of_search', 'other')",
            name="ck_placement_performance_placement",
        ),
    )
    # Spec: UNIQUE(campaign_id, date, placement) — makes the sync an upsert and
    # stops a re-run doubling a day's spend.
    op.create_index(
        "uq_placement_perf_campaign_date_placement",
        "placement_performance_daily",
        ["campaign_id", "date", "placement"],
        unique=True,
    )
    op.create_index("idx_placement_perf_date", "placement_performance_daily", ["date"])

    # Spec §8 lists placement_bidding on campaigns: the multipliers currently set
    # on Amazon, so a suggestion can show current -> proposed rather than only
    # the new value.
    op.add_column("campaigns",
                  sa.Column("placement_bidding", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("campaigns", "placement_bidding")
    op.drop_index("idx_placement_perf_date", table_name="placement_performance_daily")
    op.drop_index("uq_placement_perf_campaign_date_placement",
                  table_name="placement_performance_daily")
    op.drop_table("placement_performance_daily")

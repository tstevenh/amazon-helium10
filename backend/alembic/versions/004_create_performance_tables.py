"""004 create campaign_performance_daily, target_performance_daily

Revision ID: 004
Revises: 003
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_performance_daily",
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
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("spend", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Numeric(6, 4), nullable=True),
        sa.Column("cpc", sa.Numeric(8, 4), nullable=True),
        sa.Column("cvr", sa.Numeric(6, 4), nullable=True),
        sa.Column("acos", sa.Numeric(6, 2), nullable=True),
        sa.Column("roas", sa.Numeric(6, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("campaign_id", "date", name="uq_cpd_campaign_date"),
    )
    op.create_index("idx_cpd_campaign_date", "campaign_performance_daily", ["campaign_id", "date"])
    op.create_index("idx_cpd_date", "campaign_performance_daily", ["date"])

    op.create_table(
        "target_performance_daily",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("spend", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Numeric(6, 4), nullable=True),
        sa.Column("cpc", sa.Numeric(8, 4), nullable=True),
        sa.Column("cvr", sa.Numeric(6, 4), nullable=True),
        sa.Column("acos", sa.Numeric(6, 2), nullable=True),
        sa.Column("roas", sa.Numeric(6, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("target_id", "date", name="uq_tpd_target_date"),
    )
    op.create_index("idx_tpd_target_date", "target_performance_daily", ["target_id", "date"])
    op.create_index("idx_tpd_date", "target_performance_daily", ["date"])


def downgrade() -> None:
    op.drop_index("idx_tpd_date", table_name="target_performance_daily")
    op.drop_index("idx_tpd_target_date", table_name="target_performance_daily")
    op.drop_table("target_performance_daily")

    op.drop_index("idx_cpd_date", table_name="campaign_performance_daily")
    op.drop_index("idx_cpd_campaign_date", table_name="campaign_performance_daily")
    op.drop_table("campaign_performance_daily")

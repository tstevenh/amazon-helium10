"""scope a rule to specific campaigns

Rules currently apply to an entire marketplace. The spec's workflow 3 is
"Operator creates a Bid Rule scoped to specific campaigns" — without this an
operator cannot say "this rule only for my drinkware campaigns".

Absence of rows means profile-wide, preserving today's behaviour for every
existing rule.

Revision ID: 015
Revises: 014
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_campaign_scope",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("rule_id", "campaign_id", name="uq_rule_campaign_scope"),
    )
    op.create_index("idx_rule_campaign_scope_rule", "rule_campaign_scope", ["rule_id"])


def downgrade() -> None:
    op.drop_index("idx_rule_campaign_scope_rule", table_name="rule_campaign_scope")
    op.drop_table("rule_campaign_scope")

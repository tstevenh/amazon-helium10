"""one pending budget suggestion per rule per campaign

Spec: "PARTIAL UNIQUE(rule_id, campaign_id) WHERE status='pending'" for the
Budget Increase/Decrease suggestion type.

Without it, a daily rule evaluation would stack a new budget suggestion on the
same campaign every day until someone reviewed them — and each one would
propose a change from the ORIGINAL budget, so approving two would compound
into a change nobody intended.

Scoped to budget suggestions only. Keyword-level types already dedupe on
(profile, search_term, type) in application code.

Revision ID: 020
Revises: 019
"""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_suggestions_pending_budget_per_campaign",
        "suggestions",
        ["source_rule_id", "campaign_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'pending' AND suggestion_type IN "
            "('budget_increase', 'budget_decrease') AND source_rule_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_suggestions_pending_budget_per_campaign",
                  table_name="suggestions")

"""Scope a rule to specific ad groups, not just campaigns.

The team's report was that rules had no "add ad group / campaign" option, and
that is understated: rule_campaign_scope has existed since P4-4 and the engine
already filters on it, but no endpoint ever accepted campaign_ids — so the table
could not be populated and every rule silently ran profile-wide. A filter
honouring a table nothing can write to reads as a working feature and is not one.

Ad groups matter for the same reason they matter for search terms: one campaign's
ad groups target completely different keywords and ASINs, so "negative any term
over 60% ACoS in this campaign" is too blunt when one ad group is a broad
harvester and another is an exact-match performer.

Deliberately NOT applied to budget or placement rules: an Amazon budget belongs
to a campaign and placement adjustments are campaign-level, so an ad-group scope
there would be accepted and then ignored. The API rejects that combination
instead.

Revision ID: 025
Revises: 024
"""
import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_ad_group_scope",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ad_group_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ad_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # One row per pair. A duplicate would multiply nothing but confusion.
        sa.UniqueConstraint("rule_id", "ad_group_id", name="uq_rule_ad_group_scope"),
    )
    op.create_index("idx_rule_ad_group_scope_rule", "rule_ad_group_scope", ["rule_id"])
    # No unique constraint added to rule_campaign_scope here: it already carries
    # uq_rule_campaign_scope from an earlier revision. An attempt to add it
    # again aborted this migration; Alembic's transactional DDL rolled the whole
    # thing back, which is the only reason the database was not left half-built.


def downgrade() -> None:
    op.drop_index("idx_rule_ad_group_scope_rule", table_name="rule_ad_group_scope")
    op.drop_table("rule_ad_group_scope")

"""Sprint 3 — Rules Engine Foundation

Creates:
  - rules table (rule definitions with JSONB config, soft delete)
  - rule_executions table (execution history)
  - source_type, source_rule_id, source_rule_name columns on suggestions

Revision ID: 010
Revises: 009
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── rules table ────────────────────────────────────────────────────────
    op.create_table(
        "rules",
        sa.Column(
            "id", UUID(), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "profile_id", UUID(),
            sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name",        sa.String(200), nullable=False),
        sa.Column("description", sa.Text(),      nullable=True),
        # negative | harvest | bid
        sa.Column("rule_type",   sa.String(50),  nullable=False),
        # enabled | disabled
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default=sa.text("'enabled'"),
        ),
        sa.Column(
            "configuration_json", JSONB(), nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_by", UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at",  sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rules_profile_id", "rules", ["profile_id"])
    op.create_index("ix_rules_status",     "rules", ["status"])

    # ── rule_executions table ──────────────────────────────────────────────
    op.create_table(
        "rule_executions",
        sa.Column(
            "id", UUID(), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "rule_id", UUID(),
            sa.ForeignKey("rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id", UUID(),
            sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "started_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        # running | completed | failed
        sa.Column(
            "execution_status", sa.String(20), nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column(
            "rows_evaluated", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "suggestions_generated", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rule_executions_rule_id",    "rule_executions", ["rule_id"])
    op.create_index("ix_rule_executions_profile_id", "rule_executions", ["profile_id"])

    # ── Source tracking on suggestions ─────────────────────────────────────
    # source_type: 'engine' (built-in engine) | 'rule' (rules engine)
    op.add_column("suggestions", sa.Column(
        "source_type", sa.String(20), nullable=False,
        server_default=sa.text("'engine'"),
    ))
    op.add_column("suggestions", sa.Column(
        "source_rule_id", UUID(),
        sa.ForeignKey("rules.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("suggestions", sa.Column(
        "source_rule_name", sa.String(200), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("suggestions", "source_rule_name")
    op.drop_column("suggestions", "source_rule_id")
    op.drop_column("suggestions", "source_type")
    op.drop_index("ix_rule_executions_profile_id", table_name="rule_executions")
    op.drop_index("ix_rule_executions_rule_id",    table_name="rule_executions")
    op.drop_table("rule_executions")
    op.drop_index("ix_rules_status",     table_name="rules")
    op.drop_index("ix_rules_profile_id", table_name="rules")
    op.drop_table("rules")

"""rule templates — starting points a new operator cannot invent

Spec Part 21.2 lists /rule-templates (GET/POST) as a Phase 2 endpoint. Cloning
an existing rule was already built and §4.3 calls it "simpler and more
immediately useful", but cloning only helps once you already have a good rule.
A new marketplace starts with none, and the Rule Builder's blank condition
form gives no hint what a sensible ACoS threshold is.

is_builtin marks the seeded starting points so the UI can present them
differently from a team's own saved templates, and so a later seed run can
update them without touching anything a human wrote.

Revision ID: 016
Revises: 015
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Mirrors rules.rule_type. Constrained to the same vocabulary so a
        # template can never produce a rule the engine cannot execute.
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("configuration_json", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        # Seeded starting points vs a team's own saved templates.
        sa.Column("is_builtin", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "rule_type IN ('negative', 'harvest', 'bid', 'budget')",
            name="ck_rule_templates_rule_type",
        ),
    )
    # A builtin name is the identity a re-seed matches on, so it must be
    # unique among builtins. Team templates may repeat names freely.
    op.create_index(
        "uq_rule_templates_builtin_name",
        "rule_templates",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_builtin = true AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_rule_templates_builtin_name", table_name="rule_templates")
    op.drop_table("rule_templates")

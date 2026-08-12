"""execution audit tables + machine-readable suggestion values

Two problems this fixes.

1. The suggestions table could not express a bid change. It stored a
   search_term string and a prose reason ("add as Exact"), with no field for
   which target to modify, its current value, or the value to set. Execution
   needs all three or it has nothing to act on.

2. suggestion_actions and change_log are in the spec's V1 table list and were
   never created. suggestion_actions is the append-only record of every
   Amazon API attempt; change_log records old->new per field and is what
   makes rollback possible.

Revision ID: 014
Revises: 013
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── suggestions: make a suggestion machine-actionable ──────────────────
    op.add_column(
        "suggestions",
        sa.Column("target_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("targets.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("suggestions", sa.Column("current_value", postgresql.JSONB(), nullable=True))
    op.add_column("suggestions", sa.Column("suggested_value", postgresql.JSONB(), nullable=True))
    op.add_column("suggestions", sa.Column("priority_score", sa.Integer(), nullable=True))
    op.add_column("suggestions", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
    # The spec's inbox sorts by $ impact descending.
    op.create_index("idx_suggestions_priority", "suggestions",
                    ["status", sa.text("priority_score DESC")])

    # ── suggestion_actions: append-only attempt log ────────────────────────
    # Spec: "Append-only — never delete or update. Stores literal Amazon API
    # request/response for every execution attempt."
    op.create_table(
        "suggestion_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        # NULL performed_by means the system acted, not a person.
        sa.Column("performed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("amazon_api_request", postgresql.JSONB(), nullable=True),
        sa.Column("amazon_api_response", postgresql.JSONB(), nullable=True),
        sa.Column("amazon_api_status_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "action IN ('created','approved','rejected','deferred','executed',"
            "'execution_failed','expired','rolled_back')",
            name="ck_suggestion_actions_action",
        ),
    )
    op.create_index("idx_suggestion_actions_suggestion", "suggestion_actions",
                    ["suggestion_id", sa.text("created_at DESC")])

    # ── change_log: old -> new, powers rollback ────────────────────────────
    op.create_table(
        "change_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Kept alongside our UUID so a rollback can address Amazon directly
        # even if the local row is later soft-deleted.
        sa.Column("amazon_entity_id", sa.BigInteger(), nullable=True),
        sa.Column("field_changed", sa.String(50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("suggestions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("entity_type IN ('campaign','ad_group','target')",
                           name="ck_change_log_entity_type"),
        sa.CheckConstraint("source IN ('suggestion_execution','manual_edit','rollback')",
                           name="ck_change_log_source"),
    )
    op.create_index("idx_change_log_profile_changed", "change_log",
                    ["profile_id", sa.text("changed_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_change_log_profile_changed", table_name="change_log")
    op.drop_table("change_log")
    op.drop_index("idx_suggestion_actions_suggestion", table_name="suggestion_actions")
    op.drop_table("suggestion_actions")
    op.drop_index("idx_suggestions_priority", table_name="suggestions")
    for col in ("executed_at", "priority_score", "suggested_value",
                "current_value", "target_id"):
        op.drop_column("suggestions", col)

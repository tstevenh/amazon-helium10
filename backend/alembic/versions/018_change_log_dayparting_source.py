"""allow 'dayparting' as a change_log source

ck_change_log_source permits suggestion_execution, manual_edit and rollback.
A dayparting pause is none of those: no suggestion was approved, no human
edited anything, and it is not undoing a previous change.

Labelling it 'suggestion_execution' would have been the easy fix and a lie —
the Logs screen would then claim someone approved a suggestion that never
existed, and the audit trail is the one thing in this app that has to be
literally true.

Revision ID: 018
Revises: 017
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_change_log_source", "change_log", type_="check")
    op.create_check_constraint(
        "ck_change_log_source",
        "change_log",
        "source IN ('suggestion_execution', 'manual_edit', 'rollback', 'dayparting')",
    )


def downgrade() -> None:
    # Rows written by dayparting would violate the narrower constraint, so
    # relabel them rather than fail the downgrade.
    op.execute("UPDATE change_log SET source = 'manual_edit' WHERE source = 'dayparting'")
    op.drop_constraint("ck_change_log_source", "change_log", type_="check")
    op.create_check_constraint(
        "ck_change_log_source",
        "change_log",
        "source IN ('suggestion_execution', 'manual_edit', 'rollback')",
    )

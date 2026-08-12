"""add seller_account_id and result_json to sync_jobs

The sync_jobs table was created by an earlier migration and never used by any
code — job state lived in an in-memory dict in campaigns/router.py instead.
Wiring it up needs two additive columns: syncs are triggered per seller
account (the table only had profile_id), and the in-memory job carried a
nested result dict worth persisting.

Revision ID: 012
Revises: 011
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_jobs",
        sa.Column(
            "seller_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seller_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "sync_jobs",
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "idx_sync_jobs_account_created",
        "sync_jobs",
        ["seller_account_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_sync_jobs_account_created", table_name="sync_jobs")
    op.drop_column("sync_jobs", "result_json")
    op.drop_column("sync_jobs", "seller_account_id")

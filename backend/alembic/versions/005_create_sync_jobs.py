"""005 create sync_jobs

Revision ID: 005
Revises: 004
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_type", sa.String(30), nullable=False),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("date_range_start", sa.Date(), nullable=True),
        sa.Column("date_range_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "job_type IN ('profile_sync', 'campaign_sync', 'performance_sync')",
            name="ck_sync_jobs_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed', 'partial')",
            name="ck_sync_jobs_status",
        ),
    )
    op.create_index(
        "idx_sync_jobs_type_status",
        "sync_jobs",
        ["job_type", "status", sa.text("started_at DESC")],
    )
    op.create_index("idx_sync_jobs_profile", "sync_jobs", ["profile_id"])


def downgrade() -> None:
    op.drop_index("idx_sync_jobs_profile", table_name="sync_jobs")
    op.drop_index("idx_sync_jobs_type_status", table_name="sync_jobs")
    op.drop_table("sync_jobs")

"""allow 'sync_all' as a sync_jobs.job_type

The original ck_sync_jobs_job_type constraint enumerated one value per sync
level (profile/campaign/ad_group/target/performance), which fitted the
never-implemented design of one job row per level. The Celery task runs
structure + performance as a single unit of work, so it needs a job_type
that describes the whole run.

Existing values are preserved — this only widens the constraint.

Revision ID: 013
Revises: 012
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

_OLD = (
    "profile_sync", "campaign_sync", "ad_group_sync",
    "target_sync", "performance_sync",
)
_NEW = _OLD + ("sync_all",)


def _values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint("ck_sync_jobs_job_type", "sync_jobs", type_="check")
    op.create_check_constraint(
        "ck_sync_jobs_job_type",
        "sync_jobs",
        f"job_type IN ({_values_sql(_NEW)})",
    )


def downgrade() -> None:
    # Rows using the widened value would violate the narrowed constraint.
    op.execute("DELETE FROM sync_jobs WHERE job_type = 'sync_all'")
    op.drop_constraint("ck_sync_jobs_job_type", "sync_jobs", type_="check")
    op.create_check_constraint(
        "ck_sync_jobs_job_type",
        "sync_jobs",
        f"job_type IN ({_values_sql(_OLD)})",
    )

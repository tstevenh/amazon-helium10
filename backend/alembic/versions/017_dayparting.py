"""dayparting — scheduled campaign pause/enable by hour and weekday

Spec §8.7 and §13.7. The operator specifies the hours; the app does not
recommend them (Amazon exposes no hourly performance data for Sponsored
Products — verified 2026-08-12, three request shapes, three 400s).

DESIGN: entries describe the state a campaign SHOULD be in during a window,
not an event to fire at its edges. The executor reconciles actual state
against the schedule on every run. This matters because the host machine
sleeps: an edge-triggered design that missed a 6pm "enable" would leave ads
off indefinitely, whereas reconciliation self-heals on the next run.

hour_start is inclusive, hour_end exclusive, both 0-23/1-24 local to the
marketplace's own timezone — US, CA and MX do not share a clock, so "6am"
is three different moments.

Revision ID: 017
Revises: 016
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dayparting_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ads_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Defaults to FALSE deliberately: creating a schedule must never start
        # changing a live account. Activation is a separate, explicit act.
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        # The spec's approval-scope exception: the SCHEDULE is approved once by
        # a human, and its hourly executions then run unattended. Recording who
        # and when is what makes that exception auditable rather than implicit.
        sa.Column("activated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("activated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_dayparting_schedules_profile", "dayparting_schedules",
                    ["profile_id"])

    op.create_table(
        "dayparting_schedule_scope",
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dayparting_schedules.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                  primary_key=True),
    )

    op.create_table(
        "dayparting_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dayparting_schedules.id", ondelete="CASCADE"),
                  nullable=False),
        # 0 = Monday .. 6 = Sunday (Python's weekday(), not Amazon's).
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("hour_start", sa.SmallInteger(), nullable=False),
        sa.Column("hour_end", sa.SmallInteger(), nullable=False),
        # bid_adjust is in the spec and reserved here, but the API rejects it
        # until implemented — a stored value the executor ignores would be
        # worse than an explicit refusal.
        sa.Column("action_type", sa.String(20), nullable=False),
        sa.Column("bid_multiplier", sa.Numeric(5, 2), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6",
                           name="ck_dayparting_entries_dow"),
        sa.CheckConstraint("hour_start BETWEEN 0 AND 23",
                           name="ck_dayparting_entries_hour_start"),
        sa.CheckConstraint("hour_end BETWEEN 1 AND 24",
                           name="ck_dayparting_entries_hour_end"),
        # A window must move forward. Overnight spans are expressed as two
        # entries on adjacent days, which keeps the executor's "is now inside
        # this window" check trivial and total.
        sa.CheckConstraint("hour_end > hour_start",
                           name="ck_dayparting_entries_window_forward"),
        sa.CheckConstraint("action_type IN ('pause', 'enable', 'bid_adjust')",
                           name="ck_dayparting_entries_action_type"),
    )
    op.create_index("idx_dayparting_entries_schedule", "dayparting_entries",
                    ["schedule_id", "day_of_week"])

    # Every reconciliation the executor performs, so an operator can answer
    # "why are my ads off?" without reading worker logs. change_log records
    # what Amazon confirmed; this records the decision that led to it.
    op.create_table(
        "dayparting_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dayparting_schedules.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True),
        sa.Column("ran_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # The marketplace-local time the decision was made for, so a run is
        # explainable without recomputing timezone maths.
        sa.Column("local_time", sa.String(40), nullable=True),
        sa.Column("desired_state", sa.String(20), nullable=True),
        sa.Column("previous_state", sa.String(20), nullable=True),
        # applied | already_correct | skipped_writes_disabled | failed
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("idx_dayparting_runs_schedule_ran", "dayparting_runs",
                    ["schedule_id", "ran_at"])


def downgrade() -> None:
    op.drop_table("dayparting_runs")
    op.drop_table("dayparting_entries")
    op.drop_table("dayparting_schedule_scope")
    op.drop_index("idx_dayparting_schedules_profile",
                  table_name="dayparting_schedules")
    op.drop_table("dayparting_schedules")

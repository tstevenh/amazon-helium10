"""Dayparting restores the campaigns it paused, so "enable" windows are optional.

Before this, an unpainted hour meant "leave it alone". Painting only a pause
window 00:00-05:00 therefore paused the campaign at midnight and never turned it
back on — the ads stayed off 24 hours a day, forever, with nothing reporting it.
The operator had to remember to paint a matching enable window, and forgetting
was silent and expensive.

The obvious fix — "unpainted means enabled" — is worse: activating a schedule
would switch on campaigns a human deliberately paused (out of stock, budget
freeze), and the app would be selling things that are not there.

So the app remembers the status a campaign had BEFORE it paused it, and restores
exactly that when no window applies. It only ever undoes its own work: a
campaign a human paused has no row here, so nothing is ever force-enabled. Same
shape, and the same reasoning, as dayparting_bid_state.

Revision ID: 024
Revises: 023
"""
import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dayparting_campaign_state",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("schedule_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dayparting_schedules.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("campaign_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        # The status to return to — captured the first time this schedule
        # changes the campaign, so it is the human's own value.
        sa.Column("baseline_status", sa.String(20), nullable=False),
        # What the app last sent. NULL means it has never written. Drift is
        # measured against this, so it must be the app's own last write.
        sa.Column("last_written_status", sa.String(20), nullable=True),
        sa.Column("released_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("released_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # 'archived' is deliberately absent: Amazon cannot un-archive, so it can
        # never be a status worth restoring to.
        sa.CheckConstraint("baseline_status IN ('enabled', 'paused')",
                           name="ck_dayparting_campaign_state_baseline"),
        sa.UniqueConstraint("schedule_id", "campaign_id",
                            name="uq_dayparting_campaign_state_sched_camp"),
    )
    op.create_index("ix_dayparting_campaign_state_schedule",
                    "dayparting_campaign_state", ["schedule_id", "released_at"])


def downgrade() -> None:
    op.drop_index("ix_dayparting_campaign_state_schedule",
                  table_name="dayparting_campaign_state")
    op.drop_table("dayparting_campaign_state")

"""Dayparting bid adjustments: widen action_type, add baseline state.

The PPC team asked for what Helium 10 offers — pause, decrease bid, increase
bid — instead of pause/enable only.

The hard part is not the percentage, it is that dayparting RECONCILES rather
than firing on window edges (see modules/dayparting/service.py). "Be paused" is
a state that can be re-asserted safely every hour. "Reduce the bid 20%" is an
OPERATION, and re-applying it hourly compounds: $0.50 -> 0.40 -> 0.32 -> 0.26,
destroying the bid inside a day and starting lower again tomorrow.

So a bid adjustment has to become a state too, which needs a remembered
baseline: target = baseline * (1 +/- pct), clamped. dayparting_bid_state is
that memory. It also records what we last wrote, which is how a human's manual
edit is detected — if Amazon's bid is not the number we wrote, a person changed
it, and the app releases the target rather than silently overwriting them.

Revision ID: 023
Revises: 022
"""
import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Allow the two new actions ───────────────────────────────────────
    # 'bid_adjust' stays permitted: 017 created it as a reserved value, rows
    # may exist, and dropping it from the constraint would fail the migration.
    # The service rejects it as unimplemented; these two replace it.
    op.drop_constraint("ck_dayparting_entries_action_type", "dayparting_entries")
    op.create_check_constraint(
        "ck_dayparting_entries_action_type",
        "dayparting_entries",
        "action_type IN ('pause', 'enable', 'bid_adjust', 'decrease_bid', 'increase_bid')",
    )

    # ── 2. The adjustment itself ───────────────────────────────────────────
    # adjust_pct is always POSITIVE; the direction lives in action_type. A
    # signed percentage plus a direction gives two ways to say "down", and
    # "increase_bid by -20" is a bug waiting to happen.
    op.add_column("dayparting_entries",
                  sa.Column("adjust_pct", sa.Numeric(6, 2), nullable=True))
    # Floor and ceiling, as in Helium 10's "Min Bid" box. Optional.
    op.add_column("dayparting_entries",
                  sa.Column("min_bid", sa.Numeric(10, 2), nullable=True))
    op.add_column("dayparting_entries",
                  sa.Column("max_bid", sa.Numeric(10, 2), nullable=True))

    op.create_check_constraint(
        "ck_dayparting_entries_adjust_pct",
        "dayparting_entries",
        "adjust_pct IS NULL OR (adjust_pct > 0 AND adjust_pct <= 900)",
    )
    # A bid action without a percentage would silently do nothing every hour.
    op.create_check_constraint(
        "ck_dayparting_entries_bid_needs_pct",
        "dayparting_entries",
        "action_type NOT IN ('decrease_bid', 'increase_bid') OR adjust_pct IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_dayparting_entries_bid_bounds",
        "dayparting_entries",
        "min_bid IS NULL OR max_bid IS NULL OR min_bid <= max_bid",
    )

    # ── 3. Baseline memory ─────────────────────────────────────────────────
    op.create_table(
        "dayparting_bid_state",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("schedule_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dayparting_schedules.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("target_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False),
        # The bid to return to. Captured the first time this schedule sees the
        # target, before the app has ever written to it, so it is the human's
        # own number.
        sa.Column("baseline_bid", sa.Numeric(10, 2), nullable=False),
        # What the app last sent to Amazon. NULL means it has never written.
        # Drift is detected by comparing Amazon's value against this, so it
        # must be the app's own last write and nothing else.
        sa.Column("last_written_bid", sa.Numeric(10, 2), nullable=True),
        # Set when a human edited the bid underneath us. A released row is
        # never touched again — people outrank schedules.
        sa.Column("released_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("released_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("baseline_bid > 0", name="ck_dayparting_bid_state_baseline"),
        # One baseline per (schedule, target). Two rows would mean two
        # disagreeing opinions about what to restore.
        sa.UniqueConstraint("schedule_id", "target_id",
                            name="uq_dayparting_bid_state_schedule_target"),
    )
    # The reconciler's hot path: every active row for one schedule, hourly.
    op.create_index("ix_dayparting_bid_state_schedule", "dayparting_bid_state",
                    ["schedule_id", "released_at"])

    # ── 4. A notification type for released targets ────────────────────────
    # Releasing a target is not a failure — it is the app deferring to a human
    # — so labelling it 'dayparting_failed' would train the team to ignore
    # real failures. notification_log has no CHECK on event_type, but
    # notification_rules does, and a type nobody can write a rule for is only
    # half-supported.
    op.drop_constraint("ck_notification_rules_event_type", "notification_rules")
    op.create_check_constraint(
        "ck_notification_rules_event_type", "notification_rules",
        "event_type IN ('sync_failed', 'sync_stale', 'suggestions_pending', "
        "'execution_failed', 'dayparting_failed', 'dayparting_released', "
        "'daily_digest')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_rules_event_type", "notification_rules")
    op.create_check_constraint(
        "ck_notification_rules_event_type", "notification_rules",
        "event_type IN ('sync_failed', 'sync_stale', 'suggestions_pending', "
        "'execution_failed', 'dayparting_failed', 'daily_digest')",
    )
    op.drop_index("ix_dayparting_bid_state_schedule", table_name="dayparting_bid_state")
    op.drop_table("dayparting_bid_state")
    for name in ("ck_dayparting_entries_bid_bounds",
                 "ck_dayparting_entries_bid_needs_pct",
                 "ck_dayparting_entries_adjust_pct"):
        op.drop_constraint(name, "dayparting_entries")
    for col in ("max_bid", "min_bid", "adjust_pct"):
        op.drop_column("dayparting_entries", col)
    op.drop_constraint("ck_dayparting_entries_action_type", "dayparting_entries")
    op.create_check_constraint(
        "ck_dayparting_entries_action_type", "dayparting_entries",
        "action_type IN ('pause', 'enable', 'bid_adjust')",
    )

"""notifications — delivery log, per-event rules, and a settings table

Spec §8.9. Three tables, but the valuable one is notification_log: alerting
already existed via ALERT_WEBHOOK_URL, and it was still true that eight
consecutive failed syncs went unnoticed for a week, because an unconfigured
webhook logs to stderr and nobody reads stderr.

Logging every notification — delivered or not — makes "were we told?" a
question the app can answer about itself. The Notifications screen reads this
table, so it works even when no webhook is configured at all.

Revision ID: 019
Revises: 018
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(50), nullable=False),
        # 'email' is in the spec but there is no mail transport in this app.
        # It is permitted by the constraint and rejected by the API, so the
        # gap is explicit rather than a silently dropped notification.
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("threshold_config", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('sync_failed', 'sync_stale', 'suggestions_pending', "
            "'execution_failed', 'dayparting_failed', 'daily_digest')",
            name="ck_notification_rules_event_type",
        ),
        sa.CheckConstraint("channel IN ('slack', 'email')",
                           name="ck_notification_rules_channel"),
    )
    op.create_index("idx_notification_rules_event", "notification_rules",
                    ["event_type", "is_active"])

    op.create_table(
        "notification_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        # Nullable: a notification can be sent by built-in health checks that
        # have no configured rule behind them.
        sa.Column("notification_rule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("notification_rules.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("subject", sa.String(300), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        # 'logged_only' is the honest status when no webhook is configured:
        # the app noticed something and had nowhere to say it.
        sa.Column("delivery_status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Set when a human has seen it in the Notifications screen.
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "delivery_status IN ('delivered', 'failed', 'logged_only')",
            name="ck_notification_log_delivery_status",
        ),
    )
    op.create_index("idx_notification_log_sent", "notification_log",
                    ["sent_at"])
    op.create_index("idx_notification_log_unread", "notification_log",
                    ["read_at"], postgresql_where=sa.text("read_at IS NULL"))

    # Spec §8.9: "Phase 2 — use env-var defaults in V1". Env vars stay the
    # default; a row here overrides one, so operational knobs can be changed
    # without a container restart.
    op.create_table(
        "settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("idx_notification_log_unread", table_name="notification_log")
    op.drop_index("idx_notification_log_sent", table_name="notification_log")
    op.drop_table("notification_log")
    op.drop_index("idx_notification_rules_event", table_name="notification_rules")
    op.drop_table("notification_rules")

"""002 create seller_accounts, credentials, ads_profiles

Revision ID: 002
Revises: 001
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_seller_accounts_created_by", "seller_accounts", ["created_by"])

    op.create_table(
        "credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "seller_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seller_accounts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "ads_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "seller_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seller_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amazon_profile_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("marketplace_code", sa.String(10), nullable=False),
        sa.Column("country_code", sa.String(5), nullable=True),
        sa.Column("currency_code", sa.String(5), nullable=True),
        sa.Column("timezone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'auth_required')", name="ck_ads_profiles_status"
        ),
    )
    op.create_index(
        "idx_ads_profiles_account_marketplace",
        "ads_profiles",
        ["seller_account_id", "marketplace_code"],
    )


def downgrade() -> None:
    op.drop_index("idx_ads_profiles_account_marketplace", table_name="ads_profiles")
    op.drop_table("ads_profiles")
    op.drop_table("credentials")
    op.drop_index("idx_seller_accounts_created_by", table_name="seller_accounts")
    op.drop_table("seller_accounts")

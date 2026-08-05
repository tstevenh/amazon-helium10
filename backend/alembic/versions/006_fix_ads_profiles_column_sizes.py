"""006 fix ads_profiles marketplace_code column size

Root cause
----------
Migration 002 defined ads_profiles.marketplace_code as VARCHAR(10).
Amazon's marketplaceStringId values (e.g. ATVPDKIKX0DER, A2EUQ1WTGCTBG2)
are 13-14 characters long. This caused StringDataRightTruncation on every
real Amazon profile sync. The column fails on all 18 known Amazon marketplace
IDs — only mock data (short fake strings) could insert successfully.

Fix
---
ALTER the column to VARCHAR(50): generous headroom above the observed 14-char
maximum, consistent with the ORM model update in app/modules/accounts/models.py.

Other string columns in ads_profiles were audited and are correctly sized:
  - country_code  VARCHAR(5)   — ISO 3166-1 alpha-2, max 2 chars  ✓
  - currency_code VARCHAR(5)   — ISO 4217, max 3 chars             ✓
  - timezone      VARCHAR(50)  — longest IANA zone ~30 chars        ✓
  - status        VARCHAR(20)  — longest value 'auth_required'=13   ✓

Revision ID: 006
Revises: 005
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ads_profiles",
        "marketplace_code",
        type_=sa.String(50),
        existing_type=sa.String(10),
        existing_nullable=False,
    )


def downgrade() -> None:
    # WARNING: downgrading will truncate any marketplace_code values longer than 10 chars.
    # Only run downgrade in a dev environment with no real Amazon data.
    op.alter_column(
        "ads_profiles",
        "marketplace_code",
        type_=sa.String(10),
        existing_type=sa.String(50),
        existing_nullable=False,
    )

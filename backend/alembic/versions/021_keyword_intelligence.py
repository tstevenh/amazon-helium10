"""keyword intelligence — imported keyword snapshots and their history

Spec Part 17. An internally-owned keyword database fed by manually-uploaded
exports (Cerebro first), instead of any rank-scraping infrastructure — which
Decision 2 formally cancelled.

Import is MANUAL BY DESIGN. §17.1 is emphatic: no scheduled job ever fetches
from Helium10 or Amazon, because that would reintroduce exactly the scraping
risk Decision 2 rules out. A human exports a file and uploads it on whatever
cadence they choose.

These tables share nothing with the core PPC schema (§5.3: "ZERO tables, ZERO
API surface, ZERO UI components"), so this migration cannot destabilise
anything already working.

Revision ID: 021
Revises: 020
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ki_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # What the data REPRESENTS, distinct from when it was uploaded. Someone
        # may upload a month-old export; trends must plot it where it belongs.
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        # sha256 of the file bytes, for duplicate-import detection.
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default=sa.text("'processing'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('cerebro', 'magnet', 'brand_analytics', 'sqp', "
            "'dataforseo', 'custom_csv')",
            name="ck_ki_snapshots_source_type",
        ),
        sa.CheckConstraint("status IN ('processing', 'completed', 'failed')",
                           name="ck_ki_snapshots_status"),
    )
    op.create_index("idx_ki_snapshots_date", "ki_snapshots", ["snapshot_date"])
    op.create_index("idx_ki_snapshots_hash", "ki_snapshots", ["file_hash"])

    # A single Cerebro export commonly covers several ASINs.
    op.create_table(
        "ki_snapshot_asins",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ki_snapshots.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("asin", sa.String(20), primary_key=True),
    )

    # Master dedup table: one stable id per keyword text, so trends can join
    # across snapshots even when the source spells it differently.
    op.create_table(
        "ki_keywords",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("keyword_text", sa.Text(), nullable=False),
        # lowercase + trim + collapse whitespace, applied at insert time
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # Uniqueness is on the NORMALIZED text: "Sobriety Gifts" and
    # "sobriety  gifts" are the same keyword and must share one id, or every
    # trend line silently splits in two.
    op.create_index("uq_ki_keywords_normalized", "ki_keywords",
                    ["normalized_text"], unique=True)

    op.create_table(
        "ki_keyword_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ki_snapshots.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("keyword_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ki_keywords.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("asin", sa.String(20), nullable=True),
        sa.Column("search_volume", sa.Integer(), nullable=True),
        sa.Column("search_volume_trend_pct", sa.Numeric(10, 2), nullable=True),
        sa.Column("organic_rank", sa.Integer(), nullable=True),
        sa.Column("sponsored_rank", sa.Integer(), nullable=True),
        sa.Column("competing_products_count", sa.Integer(), nullable=True),
        sa.Column("sponsored_asins_count", sa.Integer(), nullable=True),
        sa.Column("cpc", sa.Numeric(10, 2), nullable=True),
        sa.Column("title_density", sa.Integer(), nullable=True),
        sa.Column("relevance_score", sa.Numeric(10, 2), nullable=True),
        sa.Column("estimated_sales", sa.Integer(), nullable=True),
        # The full original row. Source-specific columns we do not model are
        # never lost, so a future source needs no schema migration (§17.3).
        sa.Column("raw_row", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_ki_metrics_keyword", "ki_keyword_metrics",
                    ["keyword_id", "asin"])
    op.create_index("idx_ki_metrics_snapshot", "ki_keyword_metrics",
                    ["snapshot_id"])
    # One row per keyword x ASIN within a snapshot. A re-parse of the same file
    # must not double the history.
    op.create_index("uq_ki_metrics_snapshot_keyword_asin", "ki_keyword_metrics",
                    ["snapshot_id", "keyword_id", "asin"], unique=True)

    # Lets an operator save a reusable column mapping for a Custom CSV without
    # anyone writing a new parser (§17.3).
    op.create_table(
        "ki_column_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        # {our_field: their_column_name}
        sa.Column("mapping_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # Required for the "keywords missing from listings" opportunity (Phase 3).
    # Manually maintained in V1 — no SP-API integration — so last_updated_at
    # matters: an operator has to be able to judge staleness themselves (§17.6).
    op.create_table(
        "product_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("asin", sa.String(20), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("bullet_points", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("backend_keywords", sa.Text(), nullable=True),
        sa.Column("last_updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("product_listings")
    op.drop_table("ki_column_mappings")
    op.drop_index("uq_ki_metrics_snapshot_keyword_asin",
                  table_name="ki_keyword_metrics")
    op.drop_index("idx_ki_metrics_snapshot", table_name="ki_keyword_metrics")
    op.drop_index("idx_ki_metrics_keyword", table_name="ki_keyword_metrics")
    op.drop_table("ki_keyword_metrics")
    op.drop_index("uq_ki_keywords_normalized", table_name="ki_keywords")
    op.drop_table("ki_keywords")
    op.drop_table("ki_snapshot_asins")
    op.drop_index("idx_ki_snapshots_hash", table_name="ki_snapshots")
    op.drop_index("idx_ki_snapshots_date", table_name="ki_snapshots")
    op.drop_table("ki_snapshots")

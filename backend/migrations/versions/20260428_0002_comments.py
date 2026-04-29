"""comments table — feature track Phase 01 (anonymous comments + shares).

Revision ID: 0002_comments
Revises: 0001_initial_v1_1_schema
Create Date: 2026-04-28

Anonymous comments per montage (segment). session_id is server-side only —
used for rate limiting; never returned to clients (PRIV invariant).

created_at uses DOUBLE PRECISION (Unix seconds) to match the v1.0 tables and
keep db_sqlite/db_postgres dispatcher signatures byte-identical. The newer
TIMESTAMPTZ pattern (moderation_decisions, reports, reported_csam) is reserved
for tables that don't have a SQLite counterpart.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0002_comments"
down_revision = "0001_initial_v1_1_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE comments (
          id BIGSERIAL PRIMARY KEY,
          segment_id TEXT NOT NULL REFERENCES segments(id),
          session_id TEXT NOT NULL,
          text TEXT NOT NULL CHECK (length(text) >= 1 AND length(text) <= 300),
          created_at DOUBLE PRECISION NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX idx_comments_segment_created "
        "ON comments(segment_id, created_at DESC)"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 01 (comments) migration is one-way; rollback unsupported (D-15)"
    )

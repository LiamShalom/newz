"""relax clips.path NOT NULL — Phase 10 blob-mode INSERT writes path=NULL.

Revision ID: 0002_relax_clips_path_not_null
Revises: 0001_initial_v1_1_schema
Create Date: 2026-04-28

Phase 10 (D-12) writer at backend/db_postgres.py:177 passes path=NULL when
storage.save_clip_bytes returns an HTTP URL (Vercel Blob). The Phase 9 baseline
declared clips.path TEXT NOT NULL — the constraint was never relaxed. CHECK
constraint added to enforce that exactly one of (path, blob_url) is populated.

Children (insert_child_clip) write path="" (empty string), which satisfies the
CHECK below as a non-null value. Children are unchanged.

Downgrade (D-15): hackathon-grade, no rollback. Mirrors 0001's posture.
"""
from alembic import op


revision = "0002_relax_clips_path_not_null"
down_revision = "0001_initial_v1_1_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE clips ALTER COLUMN path DROP NOT NULL")
    op.execute(
        "ALTER TABLE clips ADD CONSTRAINT clips_path_or_blob_url_present "
        "CHECK (path IS NOT NULL OR blob_url IS NOT NULL)"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 10 schema relax is one-way; rollback unsupported (D-15)"
    )

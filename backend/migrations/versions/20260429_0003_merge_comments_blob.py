"""merge heads: 0002_comments + 0002_relax_clips_path_not_null

Revision ID: 0003_merge_comments_blob
Revises: 0002_comments, 0002_relax_clips_path_not_null
Create Date: 2026-04-29

Phase 01 (comments + shares, main branch) and Phase 10 (Vercel Blob,
liam/phase-10-blob-migration) each authored a 0002_* migration with
down_revision="0001_initial_v1_1_schema". After merging the branches,
Alembic sees two heads. This empty merge migration unifies them so
`alembic upgrade head` resolves to a single target.

Both parent migrations are independent (comments adds a new table;
relax_clips_path_not_null alters the existing clips table), so the
merge has no schema operations of its own.
"""


revision = "0003_merge_comments_blob"
down_revision = ("0002_comments", "0002_relax_clips_path_not_null")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

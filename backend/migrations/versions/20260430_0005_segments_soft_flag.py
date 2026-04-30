"""ALTER segments ADD COLUMN soft_flag — Phase 11 D-14.

Revision ID: 0005_segments_soft_flag
Revises: 0004_moderation_columns
Create Date: 2026-04-30

Phase 11 D-14 chooses the column-over-derived shape for soft_flag: cheap feed-read,
written at compile time when any cluster member's moderation_decisions row carries
a soft-flag-category signal (hate or violence). Per D-08 the broadened soft-flag
policy fires regardless of corroboration count.

Default FALSE so existing segments rows take the non-flagged value (mandatory
because segments is non-empty in any post-Wave-0 deploy).
"""
from alembic import op


revision = "0005_segments_soft_flag"
down_revision = "0004_moderation_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE segments ADD COLUMN soft_flag BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 11 segments.soft_flag ALTER is one-way; rollback unsupported"
    )

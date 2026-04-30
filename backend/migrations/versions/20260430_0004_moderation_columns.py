"""ALTER moderation_decisions + reported_csam — Phase 11 owns the column shape.

Revision ID: 0004_moderation_columns
Revises: 0003_merge_comments_blob
Create Date: 2026-04-30

Phase 9 (D-04) shipped the moderation_decisions table with id+clip_id+created_at only.
Phase 11 (D-13, post-reconciliation) lands decision/reason/provider/raw_response/
latency_ms/prompt_version + UNIQUE INDEX(clip_id, provider). Phase 11 also adds
reported_csam.ncmec_report_id BIGINT NULL for the manual-NCMEC-receipt audit trail
(reconciled D-20 — additive now, cheaper than ALTER later).

Descends from 20260429_0003_merge_comments_blob, the current head after the
Phase 01-comments + Phase 10-blob branch merge.

Downgrade: hackathon-grade, no rollback. Mirrors 0001's posture.
"""
from alembic import op


revision = "0004_moderation_columns"
down_revision = "0003_merge_comments_blob"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # moderation_decisions (Phase 11 column shape per CONTEXT D-13).
    # NOT NULL DEFAULTs are required because the Phase 9 table may be non-empty in
    # production; without defaults the ALTER fails on existing rows. The DEFAULTs
    # are immediately dropped after the ALTER lands so future inserts must supply
    # decision + provider explicitly.
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN decision TEXT NOT NULL DEFAULT 'passed'")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN reason TEXT")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN provider TEXT NOT NULL DEFAULT 'stub'")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN raw_response JSONB")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN latency_ms INTEGER")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN prompt_version TEXT")
    op.execute("ALTER TABLE moderation_decisions ALTER COLUMN decision DROP DEFAULT")
    op.execute("ALTER TABLE moderation_decisions ALTER COLUMN provider DROP DEFAULT")
    op.execute(
        "CREATE UNIQUE INDEX idx_moderation_decisions_clip_provider "
        "ON moderation_decisions(clip_id, provider)"
    )
    # reported_csam (post-reconciliation D-20: keep ncmec_report_id BIGINT NULL for
    # the manual-NCMEC-receipt audit trail. Real automated reporting deferred
    # post-pilot; pilot writes the receipt id when Liam files via report.cybertip.org).
    op.execute("ALTER TABLE reported_csam ADD COLUMN ncmec_report_id BIGINT")


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 11 moderation columns ALTER is one-way; rollback unsupported"
    )

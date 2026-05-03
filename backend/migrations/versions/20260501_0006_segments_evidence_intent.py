"""ALTER segments ADD COLUMN evidence + intent — quick task 260501-bet.

Revision ID: 0006_segments_evidence_intent
Revises: 0005_segments_soft_flag
Create Date: 2026-05-01

Adds two JSONB columns supporting the two-stage caption pipeline:

  - segments.evidence  JSONB  array of per-parent evidence objects
                              (signs, audio_transcript, visual_cues,
                               affiliations, summary)
  - segments.intent    JSONB  cluster-level synthesis output
                              (topic, what_is_happening, why_it_matters,
                               evidence_trail, derived title + caption)

Both nullable: existing rows + the OFFLINE_DEMO / classifier-fail fallback path
must continue to write segment rows without these fields. The asyncpg jsonb
codec registered in db_postgres._set_jsonb_codec round-trips JSON ↔ Python
dicts/lists transparently — callers pass json.dumps(...) on insert (matches
write_moderation_decision pattern at db_postgres.py:980).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_segments_evidence_intent"
down_revision = "0005_segments_soft_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "segments",
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "segments",
        sa.Column(
            "intent",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("segments", "intent")
    op.drop_column("segments", "evidence")

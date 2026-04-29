"""initial v1.1 schema — all 7 tables with FK relations (D-04, Hybrid bake-in).

Revision ID: 0001_initial_v1_1_schema
Revises:
Create Date: 2026-04-28

Phase 9 (D-04): Lands all 7 v1.1 tables. Phases 10-12 do ALTER ADD COLUMN only.

Forward-compat columns (D-05): clips.blob_url (Phase 10) and clips.is_hidden
(Phase 11) are nullable so future ALTERs don't have to backfill existing rows.

MOD-09 statutory retention (RESEARCH Pitfall 2): the
reported_csam.content_preserved_until column is created without an encoded
duration. Phase 11 (the writer) chooses the retention period — the post-2024
REPORT Act amendment to 18 U.S.C. § 2258A sets a 1-year minimum; the
REQUIREMENTS.md figure (pre-amendment, three months) is stale and must be
reconciled before Phase 11 ships.

Downgrade (D-15): hackathon-grade, no rollback. Failed deploy = manual
investigation.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0001_initial_v1_1_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- v1.0 tables (lift from db_sqlite.py SCHEMA_SQL + inline ALTERs) ----
    op.execute("""
        CREATE TABLE clips (
          id TEXT PRIMARY KEY,
          path TEXT NOT NULL,
          lat DOUBLE PRECISION NOT NULL,
          lng DOUBLE PRECISION NOT NULL,
          ts DOUBLE PRECISION NOT NULL,
          duration_sec DOUBLE PRECISION,
          embedding_status TEXT NOT NULL DEFAULT 'pending',
          embed_latency_ms INTEGER,
          cluster_id TEXT,
          session_id TEXT,
          created_at DOUBLE PRECISION NOT NULL,
          -- v1.0 ALTERs absorbed inline (db_sqlite.py:88-102):
          parent_id TEXT REFERENCES clips(id),
          start_offset_sec DOUBLE PRECISION DEFAULT 0,
          end_offset_sec DOUBLE PRECISION,
          -- D-05: nullable forward-compat columns (Phases 10/11 populate without re-ALTER):
          blob_url TEXT,
          is_hidden BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX idx_clips_created_at ON clips(created_at)")
    op.execute("CREATE INDEX idx_clips_parent_id ON clips(parent_id)")

    op.execute("""
        CREATE TABLE clip_embeddings (
          clip_id TEXT PRIMARY KEY REFERENCES clips(id),
          vector BYTEA NOT NULL,
          latency_ms DOUBLE PRECISION,
          created_at DOUBLE PRECISION
        )
    """)

    op.execute("""
        CREATE TABLE clusters (
          id TEXT PRIMARY KEY,
          centroid BYTEA,
          centroid_lat DOUBLE PRECISION,
          centroid_lng DOUBLE PRECISION,
          median_ts DOUBLE PRECISION,
          member_count INTEGER NOT NULL DEFAULT 0,
          created_at DOUBLE PRECISION NOT NULL,
          updated_at DOUBLE PRECISION NOT NULL,
          -- v1.0 ALTERs absorbed inline (db_sqlite.py:77-83):
          compile_in_flight INTEGER NOT NULL DEFAULT 0,
          last_compile_at DOUBLE PRECISION
        )
    """)

    op.execute("""
        CREATE TABLE segments (
          id TEXT PRIMARY KEY,
          cluster_id TEXT NOT NULL REFERENCES clusters(id),
          ordered_clip_ids TEXT NOT NULL,
          caption TEXT,
          location TEXT,
          source_count INTEGER NOT NULL,
          created_at DOUBLE PRECISION NOT NULL,
          -- v1.0 ALTERs absorbed inline (db_sqlite.py:107-118):
          video_url TEXT,
          title TEXT
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX idx_segments_cluster_id ON segments(cluster_id)"
    )

    # ---- v1.1 tables (Phase 9 creates, owners populate columns) ----
    op.execute("""
        CREATE TABLE moderation_decisions (
          -- Phase 11 owns the column shape. Phase 9 lands the table + FK only.
          id TEXT PRIMARY KEY,
          clip_id TEXT NOT NULL REFERENCES clips(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX idx_moderation_decisions_clip_id "
        "ON moderation_decisions(clip_id)"
    )

    op.execute("""
        CREATE TABLE reports (
          -- Phase 12 owns the column shape. Phase 9 lands the table + FK only.
          id TEXT PRIMARY KEY,
          segment_id TEXT NOT NULL REFERENCES segments(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_reports_segment_id ON reports(segment_id)")

    op.execute("""
        CREATE TABLE reported_csam (
          -- MOD-09 / 18 U.S.C. § 2258A. Per RESEARCH Pitfall 2 + 2024 REPORT Act
          -- amendment, statutory retention is 1 year (NOT the stale pre-amendment
          -- three-month figure carried in REQUIREMENTS.md). Phase 11 (the writer)
          -- chooses the duration. Phase 9 ships only the column shape.
          id TEXT PRIMARY KEY,
          content_hash TEXT NOT NULL,
          content_preserved_until TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX idx_reported_csam_content_hash "
        "ON reported_csam(content_hash)"
    )


def downgrade() -> None:
    # D-15: hackathon-grade, no rollback support. Failed deploy = manual
    # investigation; do not implement automatic schema teardown.
    raise NotImplementedError(
        "Phase 9 initial migration is one-way; rollback unsupported (D-15)"
    )

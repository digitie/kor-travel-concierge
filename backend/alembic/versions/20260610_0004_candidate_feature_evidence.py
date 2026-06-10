"""candidate and mapping feature evidence fields.

Revision ID: 20260610_0004
Revises: 20260610_0003
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260610_0004"
down_revision = "20260610_0003"
branch_labels = None
depends_on = None


def _add_evidence_columns(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("source_channel_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("source_playlist_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("analysis_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column(
            "source_kind",
            sa.String(length=32),
            nullable=False,
            server_default="transcript",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "provider_evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "feature_export_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.alter_column(table_name, "source_kind", server_default=None)
    op.alter_column(table_name, "feature_export_status", server_default=None)


def _add_evidence_constraints_and_indexes(table_name: str) -> None:
    prefix = "epc" if table_name == "extracted_place_candidates" else "vpm"
    op.create_foreign_key(
        f"fk_{prefix}_source_channel",
        table_name,
        "youtube_channels",
        ["source_channel_id"],
        ["channel_id"],
        ondelete="NO ACTION",
    )
    op.create_foreign_key(
        f"fk_{prefix}_source_playlist",
        table_name,
        "youtube_playlists",
        ["source_playlist_id"],
        ["playlist_id"],
        ondelete="NO ACTION",
    )
    op.create_foreign_key(
        f"fk_{prefix}_analysis_run",
        table_name,
        "youtube_video_analysis_runs",
        ["analysis_run_id"],
        ["id"],
        ondelete="NO ACTION",
    )
    op.create_index(
        f"ix_{prefix}_source_channel_id",
        table_name,
        ["source_channel_id"],
    )
    op.create_index(
        f"ix_{prefix}_source_playlist_id",
        table_name,
        ["source_playlist_id"],
    )
    op.create_index(
        f"ix_{prefix}_analysis_run_id",
        table_name,
        ["analysis_run_id"],
    )
    op.create_index(
        f"ix_{prefix}_feature_export_status",
        table_name,
        ["feature_export_status"],
    )
    op.create_index(
        f"ix_{prefix}_feature_status_created",
        table_name,
        ["feature_export_status", "created_at", "id"],
    )
    op.create_index(
        f"ix_{prefix}_provider_evidence_json_gin",
        table_name,
        ["provider_evidence_json"],
        postgresql_using="gin",
    )


def _drop_evidence_constraints_and_indexes(table_name: str) -> None:
    prefix = "epc" if table_name == "extracted_place_candidates" else "vpm"
    op.drop_index(f"ix_{prefix}_provider_evidence_json_gin", table_name=table_name)
    op.drop_index(f"ix_{prefix}_feature_status_created", table_name=table_name)
    op.drop_index(f"ix_{prefix}_feature_export_status", table_name=table_name)
    op.drop_index(f"ix_{prefix}_analysis_run_id", table_name=table_name)
    op.drop_index(f"ix_{prefix}_source_playlist_id", table_name=table_name)
    op.drop_index(f"ix_{prefix}_source_channel_id", table_name=table_name)
    op.drop_constraint(
        f"fk_{prefix}_analysis_run",
        table_name,
        type_="foreignkey",
    )
    op.drop_constraint(
        f"fk_{prefix}_source_playlist",
        table_name,
        type_="foreignkey",
    )
    op.drop_constraint(
        f"fk_{prefix}_source_channel",
        table_name,
        type_="foreignkey",
    )


def _drop_evidence_columns(table_name: str) -> None:
    op.drop_column(table_name, "feature_export_status")
    op.drop_column(table_name, "provider_evidence_json")
    op.drop_column(table_name, "source_kind")
    op.drop_column(table_name, "analysis_run_id")
    op.drop_column(table_name, "source_playlist_id")
    op.drop_column(table_name, "source_channel_id")


def upgrade() -> None:
    _add_evidence_columns("extracted_place_candidates")
    _add_evidence_columns("video_place_mappings")
    op.execute(
        """
        UPDATE extracted_place_candidates AS c
        SET source_channel_id = v.channel_id
        FROM youtube_videos AS v
        WHERE c.video_id = v.video_id
          AND c.source_channel_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE extracted_place_candidates
        SET feature_export_status = 'ready'
        WHERE match_status IN ('matched', 'user_corrected')
        """
    )
    op.execute(
        """
        UPDATE video_place_mappings AS m
        SET source_channel_id = v.channel_id,
            feature_export_status = 'ready'
        FROM youtube_videos AS v
        WHERE m.video_id = v.video_id
          AND m.source_channel_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE video_place_mappings AS m
        SET source_channel_id = COALESCE(c.source_channel_id, m.source_channel_id),
            source_playlist_id = c.source_playlist_id,
            analysis_run_id = c.analysis_run_id,
            source_kind = c.source_kind,
            provider_evidence_json = c.provider_evidence_json,
            feature_export_status = c.feature_export_status
        FROM extracted_place_candidates AS c
        WHERE m.place_candidate_id = c.id
        """
    )
    _add_evidence_constraints_and_indexes("extracted_place_candidates")
    _add_evidence_constraints_and_indexes("video_place_mappings")


def downgrade() -> None:
    _drop_evidence_constraints_and_indexes("video_place_mappings")
    _drop_evidence_constraints_and_indexes("extracted_place_candidates")
    _drop_evidence_columns("video_place_mappings")
    _drop_evidence_columns("extracted_place_candidates")

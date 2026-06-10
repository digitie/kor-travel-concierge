"""YouTube source 정규화 테이블 추가.

Revision ID: 20260610_0002
Revises: 20260610_0001
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260610_0002"
down_revision = "20260610_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_channels",
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("handle", sa.String(length=128), nullable=True),
        sa.Column("custom_url", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=1024), nullable=True),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("video_count", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gemini_summary", sa.Text(), nullable=True),
        sa.Column("gemini_summary_model", sa.String(length=64), nullable=True),
        sa.Column("gemini_summary_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("channel_id"),
    )

    op.execute(
        """
        INSERT INTO youtube_channels (channel_id, title, last_seen_at, created_at)
        SELECT DISTINCT
            channel_id,
            COALESCE(NULLIF(channel_name, ''), channel_id),
            NOW(),
            NOW()
        FROM youtube_videos
        WHERE channel_id IS NOT NULL AND channel_id <> ''
        ON CONFLICT (channel_id) DO NOTHING
        """
    )

    op.add_column(
        "youtube_videos",
        sa.Column("canonical_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("thumbnail_url", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("default_language", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("gemini_url_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column(
            "gemini_url_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("gemini_url_summary_model", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("gemini_url_summary_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("transcript_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("reconciled_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column(
            "reconciled_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("reconciled_summary_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE youtube_videos
        SET canonical_url = COALESCE(NULLIF(url, ''), 'https://www.youtube.com/watch?v=' || video_id)
        WHERE canonical_url IS NULL
        """
    )
    op.create_foreign_key(
        "fk_youtube_videos_channel_id_youtube_channels",
        "youtube_videos",
        "youtube_channels",
        ["channel_id"],
        ["channel_id"],
        ondelete="NO ACTION",
    )
    op.create_index(
        "ix_youtube_videos_tags_json_gin",
        "youtube_videos",
        ["tags_json"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_youtube_videos_gemini_url_summary_json_gin",
        "youtube_videos",
        ["gemini_url_summary_json"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_youtube_videos_reconciled_summary_json_gin",
        "youtube_videos",
        ["reconciled_summary_json"],
        postgresql_using="gin",
    )

    op.create_table(
        "youtube_playlists",
        sa.Column("playlist_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=1024), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_item_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["youtube_channels.channel_id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("playlist_id"),
    )
    op.create_index("ix_youtube_playlists_channel_id", "youtube_playlists", ["channel_id"])

    op.create_table(
        "youtube_playlist_videos",
        sa.Column("playlist_id", sa.String(length=64), nullable=False),
        sa.Column("video_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("playlist_item_id", sa.String(length=128), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["playlist_id"],
            ["youtube_playlists.playlist_id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["youtube_videos.video_id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("playlist_id", "video_id"),
    )
    op.create_index(
        "ix_youtube_playlist_videos_video_id",
        "youtube_playlist_videos",
        ["video_id"],
    )

    op.create_table(
        "youtube_video_analysis_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=32), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("input_asset_id", sa.Integer(), nullable=True),
        sa.Column(
            "summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["input_asset_id"],
            ["media_assets.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["youtube_videos.video_id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_youtube_video_analysis_runs_video_id",
        "youtube_video_analysis_runs",
        ["video_id"],
    )
    op.create_index(
        "ix_youtube_video_analysis_runs_run_type",
        "youtube_video_analysis_runs",
        ["run_type"],
    )
    op.create_index(
        "ix_youtube_video_analysis_runs_state",
        "youtube_video_analysis_runs",
        ["state"],
    )
    op.create_index(
        "ix_youtube_video_analysis_runs_input_asset_id",
        "youtube_video_analysis_runs",
        ["input_asset_id"],
    )
    op.create_index(
        "ix_youtube_video_analysis_runs_video_type_state",
        "youtube_video_analysis_runs",
        ["video_id", "run_type", "state"],
    )
    op.create_index(
        "ix_youtube_video_analysis_runs_summary_json_gin",
        "youtube_video_analysis_runs",
        ["summary_json"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_youtube_video_analysis_runs_summary_json_gin",
        table_name="youtube_video_analysis_runs",
    )
    op.drop_index(
        "ix_youtube_video_analysis_runs_video_type_state",
        table_name="youtube_video_analysis_runs",
    )
    op.drop_index(
        "ix_youtube_video_analysis_runs_input_asset_id",
        table_name="youtube_video_analysis_runs",
    )
    op.drop_index(
        "ix_youtube_video_analysis_runs_state",
        table_name="youtube_video_analysis_runs",
    )
    op.drop_index(
        "ix_youtube_video_analysis_runs_run_type",
        table_name="youtube_video_analysis_runs",
    )
    op.drop_index(
        "ix_youtube_video_analysis_runs_video_id",
        table_name="youtube_video_analysis_runs",
    )
    op.drop_table("youtube_video_analysis_runs")

    op.drop_index(
        "ix_youtube_playlist_videos_video_id",
        table_name="youtube_playlist_videos",
    )
    op.drop_table("youtube_playlist_videos")

    op.drop_index("ix_youtube_playlists_channel_id", table_name="youtube_playlists")
    op.drop_table("youtube_playlists")

    op.drop_index(
        "ix_youtube_videos_reconciled_summary_json_gin",
        table_name="youtube_videos",
    )
    op.drop_index(
        "ix_youtube_videos_gemini_url_summary_json_gin",
        table_name="youtube_videos",
    )
    op.drop_index("ix_youtube_videos_tags_json_gin", table_name="youtube_videos")
    op.drop_constraint(
        "fk_youtube_videos_channel_id_youtube_channels",
        "youtube_videos",
        type_="foreignkey",
    )
    op.drop_column("youtube_videos", "reconciled_summary_at")
    op.drop_column("youtube_videos", "reconciled_summary_json")
    op.drop_column("youtube_videos", "reconciled_summary")
    op.drop_column("youtube_videos", "transcript_summary")
    op.drop_column("youtube_videos", "gemini_url_summary_at")
    op.drop_column("youtube_videos", "gemini_url_summary_model")
    op.drop_column("youtube_videos", "gemini_url_summary_json")
    op.drop_column("youtube_videos", "gemini_url_summary")
    op.drop_column("youtube_videos", "tags_json")
    op.drop_column("youtube_videos", "default_language")
    op.drop_column("youtube_videos", "thumbnail_url")
    op.drop_column("youtube_videos", "duration_seconds")
    op.drop_column("youtube_videos", "canonical_url")

    op.drop_table("youtube_channels")

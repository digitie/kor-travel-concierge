"""PostgreSQL/PostGIS 초기 schema.

Revision ID: 20260610_0001
Revises:
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op
import geoalchemy2
import sqlalchemy as sa

revision = "20260610_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("current_message", sa.Text(), nullable=True),
        sa.Column("status_log_json", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_runs_state", "crawl_runs", ["state"])
    op.create_index(
        "ix_crawl_runs_claim_pending",
        "crawl_runs",
        ["state", "id"],
    )

    op.create_table(
        "search_keywords",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seed_keyword", sa.String(length=255), nullable=False),
        sa.Column("derived_keyword", sa.String(length=255), nullable=True),
        sa.Column("season_context", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "seed_keyword",
            "derived_keyword",
            "season_context",
            name="uq_search_keywords_seed_derived_season",
        ),
    )
    op.create_index("ix_search_keywords_seed_keyword", "search_keywords", ["seed_keyword"])

    op.create_table(
        "source_targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("source_value", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_crawl_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_type",
            "source_value",
            name="uq_source_targets_target_type_source_value",
        ),
    )
    op.create_index(
        "ix_source_targets_active_next_crawl",
        "source_targets",
        ["is_active", "next_crawl_at", "id"],
    )

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "youtube_videos",
        sa.Column("video_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("channel_name", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("engagement_score", sa.Float(), nullable=True),
        sa.Column("description_raw", sa.Text(), nullable=True),
        sa.Column("description_gemini_corrected", sa.Text(), nullable=True),
        sa.Column("description_gemini_corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description_gemini_model", sa.String(length=64), nullable=True),
        sa.Column("crawl_status", sa.String(length=32), nullable=False),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("video_id"),
    )
    op.create_index("ix_youtube_videos_channel_id", "youtube_videos", ["channel_id"])

    op.create_table(
        "travel_places",
        sa.Column("place_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("gemini_enriched_description", sa.Text(), nullable=True),
        sa.Column("description_review_status", sa.String(length=32), nullable=False),
        sa.Column("official_address", sa.String(length=512), nullable=True),
        sa.Column("road_address", sa.String(length=512), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry(
                geometry_type="POINT",
                srid=4326,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("api_source", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("is_geocoded", sa.Boolean(), nullable=False),
        sa.Column("detailed_research_content", sa.Text(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("place_id"),
    )
    op.create_index("ix_travel_places_name", "travel_places", ["name"])
    op.create_index("ix_travel_places_latitude", "travel_places", ["latitude"])
    op.create_index("ix_travel_places_longitude", "travel_places", ["longitude"])
    op.create_index(
        "ix_travel_places_geom_gist",
        "travel_places",
        ["geom"],
        postgresql_using="gist",
    )

    op.create_table(
        "extracted_place_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=32), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("ai_place_name", sa.String(length=255), nullable=False),
        sa.Column("speaker_note", sa.Text(), nullable=True),
        sa.Column("location_hint", sa.Text(), nullable=True),
        sa.Column("timestamp_start", sa.String(length=16), nullable=True),
        sa.Column("timestamp_end", sa.String(length=16), nullable=True),
        sa.Column("candidate_category", sa.String(length=64), nullable=True),
        sa.Column("match_status", sa.String(length=32), nullable=False),
        sa.Column("matched_place_id", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["matched_place_id"],
            ["travel_places.place_id"],
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
        "ix_extracted_place_candidates_video_id",
        "extracted_place_candidates",
        ["video_id"],
    )
    op.create_index(
        "ix_extracted_place_candidates_match_status",
        "extracted_place_candidates",
        ["match_status"],
    )
    op.create_index(
        "ix_extracted_place_candidates_matched_place_id",
        "extracted_place_candidates",
        ["matched_place_id"],
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("video_id", sa.String(length=32), nullable=True),
        sa.Column("place_id", sa.Integer(), nullable=True),
        sa.Column("storage_provider", sa.String(length=16), nullable=False),
        sa.Column("bucket", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("object_uri", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("retention_policy", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["travel_places.place_id"], ondelete="NO ACTION"),
        sa.ForeignKeyConstraint(["video_id"], ["youtube_videos.video_id"], ondelete="NO ACTION"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_assets_asset_type", "media_assets", ["asset_type"])
    op.create_index("ix_media_assets_video_id", "media_assets", ["video_id"])
    op.create_index("ix_media_assets_place_id", "media_assets", ["place_id"])

    op.create_table(
        "video_place_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=32), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("place_candidate_id", sa.Integer(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=False),
        sa.Column("speaker_note", sa.Text(), nullable=True),
        sa.Column("timestamp_start", sa.String(length=16), nullable=True),
        sa.Column("timestamp_end", sa.String(length=16), nullable=True),
        sa.Column("frame_asset_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["frame_asset_id"],
            ["media_assets.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["place_candidate_id"],
            ["extracted_place_candidates.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["place_id"],
            ["travel_places.place_id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["youtube_videos.video_id"],
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_place_mappings_video_id", "video_place_mappings", ["video_id"])
    op.create_index("ix_video_place_mappings_place_id", "video_place_mappings", ["place_id"])
    op.create_index(
        "ix_video_place_mappings_place_candidate_id",
        "video_place_mappings",
        ["place_candidate_id"],
    )
    op.create_index(
        "ix_video_place_mappings_frame_asset_id",
        "video_place_mappings",
        ["frame_asset_id"],
    )


def downgrade() -> None:
    op.drop_table("video_place_mappings")
    op.drop_table("media_assets")
    op.drop_table("extracted_place_candidates")
    op.drop_index("ix_travel_places_geom_gist", table_name="travel_places")
    op.drop_table("travel_places")
    op.drop_table("youtube_videos")
    op.drop_table("system_settings")
    op.drop_table("source_targets")
    op.drop_table("search_keywords")
    op.drop_table("crawl_runs")
    op.drop_table("audit_logs")

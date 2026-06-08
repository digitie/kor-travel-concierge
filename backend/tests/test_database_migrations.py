"""SQLite 기존 DB 보정 경로 테스트."""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import (
    ensure_video_place_mapping_repeatable,
    run_schema_migrations,
)
from app.models import TravelPlace, VideoPlaceMapping, YoutubeVideo


async def test_ensure_video_place_mapping_repeatable_rebuilds_legacy_unique_table(
    engine, session_factory
):
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE video_place_mappings;"))
        await conn.execute(
            text(
                """
                CREATE TABLE video_place_mappings (
                    id INTEGER NOT NULL,
                    video_id VARCHAR(32) NOT NULL,
                    place_id INTEGER NOT NULL,
                    place_candidate_id INTEGER,
                    ai_summary TEXT NOT NULL,
                    speaker_note TEXT,
                    timestamp_start VARCHAR(16),
                    timestamp_end VARCHAR(16),
                    frame_asset_id INTEGER,
                    created_at DATETIME NOT NULL,
                    PRIMARY KEY (id),
                    CONSTRAINT uq_video_place_mappings_video_place UNIQUE (video_id, place_id),
                    FOREIGN KEY(video_id) REFERENCES youtube_videos (video_id),
                    FOREIGN KEY(place_id) REFERENCES travel_places (place_id),
                    FOREIGN KEY(place_candidate_id) REFERENCES extracted_place_candidates (id),
                    FOREIGN KEY(frame_asset_id) REFERENCES media_assets (id)
                );
                """
            )
        )

        await ensure_video_place_mapping_repeatable(conn)

        result = await conn.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'video_place_mappings';"
            )
        )
        created_sql = result.scalar_one()
        assert "uq_video_place_mappings_video_place" not in created_sql
        assert "ON DELETE NO ACTION" in created_sql

    async with session_factory() as session:
        video = YoutubeVideo(video_id="v-repeat", title="반복 장소", url="u", channel_id="c")
        place = TravelPlace(name="월정리 해변", latitude=33.5563, longitude=126.7958)
        session.add_all([video, place])
        await session.commit()
        await session.refresh(place)

        session.add_all(
            [
                VideoPlaceMapping(
                    video_id=video.video_id,
                    place_id=place.place_id,
                    ai_summary="첫 번째 언급",
                    timestamp_start="00:01:00",
                ),
                VideoPlaceMapping(
                    video_id=video.video_id,
                    place_id=place.place_id,
                    ai_summary="두 번째 언급",
                    timestamp_start="00:08:30",
                ),
            ]
        )
        await session.commit()


async def test_run_schema_migrations_records_and_skips_applied_ids(engine):
    calls = []

    async def migration(conn):
        calls.append("run")
        await conn.execute(
            text("CREATE TABLE IF NOT EXISTS migration_marker (id INTEGER);")
        )

    async with engine.begin() as conn:
        await run_schema_migrations(conn, migrations=(("test_once", migration),))
        await run_schema_migrations(conn, migrations=(("test_once", migration),))
        result = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = 'test_once';")
        )
        applied_id = result.scalar_one()

    assert calls == ["run"]
    assert applied_id == "test_once"

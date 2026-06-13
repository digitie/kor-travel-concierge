"""장소 내보내기 직렬화 테스트."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from ktc.services.place_export_service import build_place_export
from ktc.services.place_service import PlaceSourceMention, PlaceSummary


def test_place_export_strips_invalid_xml_control_characters():
    summary = PlaceSummary(
        place=SimpleNamespace(
            place_id=1,
            name="월정리\x01해변",
            category="해변\x0b",
            official_address="제주시\x08구좌읍",
            road_address=None,
            latitude=33.5563,
            longitude=126.7958,
        ),
        mention_count=1,
        source_channel_count=1,
        source_videos=[
            PlaceSourceMention(
                mapping_id=1,
                video_id="video-1",
                video_title="제주\x02여행",
                video_url="https://youtu.be/video-1",
                channel_id="channel-1",
                channel_name="제주\x03채널",
                timestamp_start="00:01:00",
                timestamp_end=None,
                ai_summary="대표\x1f장면",
                speaker_note=None,
            )
        ],
    )

    for export_format in ("xlsx", "gpx", "kml"):
        body, _, _ = build_place_export([summary], export_format)
        xml_payload = _extract_xml_payload(body, export_format)

        ET.fromstring(xml_payload)
        assert "\x01" not in xml_payload
        assert "\x02" not in xml_payload
        assert "\x03" not in xml_payload
        assert "\x08" not in xml_payload
        assert "\x0b" not in xml_payload
        assert "\x1f" not in xml_payload
        assert "월정리해변" in xml_payload
        assert "제주채널" in xml_payload


def _extract_xml_payload(body: bytes, export_format: str) -> str:
    if export_format == "xlsx":
        with ZipFile(BytesIO(body)) as archive:
            return archive.read("xl/worksheets/sheet1.xml").decode()
    return body.decode()

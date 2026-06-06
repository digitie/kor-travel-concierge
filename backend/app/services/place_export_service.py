"""장소 목록 내보내기 생성 서비스."""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.place_service import PlaceSourceMention, PlaceSummary

ExportPayload = tuple[bytes, str, str]


def build_place_export(summaries: list[PlaceSummary], export_format: str) -> ExportPayload:
    """장소 목록을 요청한 파일 형식으로 직렬화한다."""
    normalized = export_format.lower()
    if normalized == "xlsx":
        return (
            _build_xlsx(summaries),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "tripmate-places.xlsx",
        )
    if normalized == "gpx":
        return (_build_gpx(summaries), "application/gpx+xml", "tripmate-places.gpx")
    if normalized == "kml":
        return (
            _build_kml(summaries),
            "application/vnd.google-earth.kml+xml",
            "tripmate-places.kml",
        )
    raise ValueError(f"지원하지 않는 export 형식: {export_format}")


def _build_xlsx(summaries: list[PlaceSummary]) -> bytes:
    rows = [
        [
            "장소 ID",
            "장소명",
            "카테고리",
            "공식 주소",
            "도로명 주소",
            "위도",
            "경도",
            "언급 횟수",
            "유튜버 수",
            "유튜버",
            "영상 제목",
            "영상 URL",
            "타임스탬프",
            "언급 요약",
        ]
    ]
    for summary in summaries:
        mentions = summary.source_videos or [None]
        for mention in mentions:
            rows.append(_xlsx_row(summary, mention))

    worksheet = _worksheet_xml(rows)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml())
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


def _xlsx_row(summary: PlaceSummary, mention: PlaceSourceMention | None) -> list[str]:
    place = summary.place
    return [
        str(place.place_id),
        place.name,
        place.category or "",
        place.official_address or "",
        place.road_address or "",
        f"{place.latitude:.7f}",
        f"{place.longitude:.7f}",
        str(summary.mention_count),
        str(summary.source_channel_count),
        _channel_label(mention) if mention else "",
        mention.video_title if mention else "",
        mention.video_url if mention else "",
        _timestamp_label(mention) if mention else "",
        mention.ai_summary if mention else "",
    ]


def _worksheet_xml(rows: list[list[str]]) -> str:
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{_column_name(column_index)}{row_index}"
            cells.append(
                f'<c r="{cell_ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        f'{"".join(body)}'
        "</sheetData>"
        "</worksheet>"
    )


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="장소 목록" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


def _workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )


def _build_gpx(summaries: list[PlaceSummary]) -> bytes:
    waypoints = []
    for summary in summaries:
        place = summary.place
        waypoints.append(
            '<wpt lat="{lat:.7f}" lon="{lng:.7f}">'
            "<name>{name}</name>"
            "<desc>{desc}</desc>"
            "</wpt>".format(
                lat=place.latitude,
                lng=place.longitude,
                name=escape(place.name),
                desc=escape(_description(summary)),
            )
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="TripMate Agent" '
        'xmlns="http://www.topografix.com/GPX/1/1">'
        f'{"".join(waypoints)}'
        "</gpx>"
    )
    return xml.encode("utf-8")


def _build_kml(summaries: list[PlaceSummary]) -> bytes:
    placemarks = []
    for summary in summaries:
        place = summary.place
        placemarks.append(
            "<Placemark>"
            f"<name>{escape(place.name)}</name>"
            f"<description>{escape(_description(summary))}</description>"
            "<Point>"
            f"<coordinates>{place.longitude:.7f},{place.latitude:.7f},0</coordinates>"
            "</Point>"
            "</Placemark>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2">'
        "<Document>"
        "<name>TripMate 장소 목록</name>"
        f'{"".join(placemarks)}'
        "</Document>"
        "</kml>"
    )
    return xml.encode("utf-8")


def _description(summary: PlaceSummary) -> str:
    place = summary.place
    lines = [
        f"카테고리: {place.category or '미분류'}",
        f"언급 횟수: {summary.mention_count}",
        f"유튜버 수: {summary.source_channel_count}",
        f"주소: {place.official_address or place.road_address or '-'}",
    ]
    for mention in summary.source_videos:
        lines.append(
            " / ".join(
                value
                for value in (
                    _channel_label(mention),
                    mention.video_title,
                    _timestamp_label(mention),
                    mention.video_url,
                )
                if value
            )
        )
    return "\n".join(lines)


def _channel_label(mention: PlaceSourceMention | None) -> str:
    if mention is None:
        return ""
    return mention.channel_name or mention.channel_id


def _timestamp_label(mention: PlaceSourceMention | None) -> str:
    if mention is None:
        return ""
    if mention.timestamp_start and mention.timestamp_end:
        return f"{mention.timestamp_start}-{mention.timestamp_end}"
    return mention.timestamp_start or mention.timestamp_end or ""

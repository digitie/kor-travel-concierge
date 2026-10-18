"""실제 Concierge HTTP 응답을 Map adapter/적재기에 전달하는 격리 수용 검증.

Map checkout의 PYTHONPATH와 pytest 설정으로 별도 실행한다. 운영 DB 사용 금지.
입력은 test_geo_refresh_http_acceptance가 실제 loopback HTTP로 읽은 synthetic 응답이다.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra.feature_repo import load_bundles
from kortravelmap.providers.kor_travel_concierge import (
    kor_travel_concierge_items_to_bundles,
)
from sqlalchemy import text

pytest_plugins = ["tests.integration.conftest"]
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scenario", ["changed", "partial_503", "cancel_resume"])
async def test_actual_concierge_changes_survive_map_load(migrated_session, scenario):
    evidence = json.loads(
        (
            Path(os.environ["KTC_TRACK1_HTTP_EVIDENCE_DIR"]) / f"{scenario}.json"
        ).read_text()
    )
    assert evidence["status"] == "PASS"
    session = migrated_session

    async def convert(items, token):
        return await kor_travel_concierge_items_to_bundles(
            items,
            fetched_at=datetime(2026, 10, 19, tzinfo=UTC),
            current_data_token=token,
        )

    def context(token):
        return GeoLoadContext(
            geo_applied=GeoApplied(reverse=True, geocode=False),
            current_dataset=DatasetRef(
                version_token="dv1-" + "c" * 32, data_token=token
            ),
        )

    async def rows():
        return {
            str(r.feature_id): (r.legal_dong_code, r.row_revision)
            for r in await session.execute(
                text(
                    "SELECT feature_id, legal_dong_code, row_revision FROM feature.features"
                )
            )
        }

    old = await convert(evidence["old"]["items"], evidence["old_token"])
    new = await convert(evidence["changed"]["items"], evidence["new_token"])
    count = len(evidence["old"]["items"])
    assert len(old) == len(new) == count
    assert {b.feature.feature_id for b in old} == {b.feature.feature_id for b in new}
    assert all(b.feature.address.bjd_code == "1168010100" for b in new)
    await load_bundles(session, old, geo=context(evidence["old_token"]))
    before = await rows()
    assert len(before) == count
    assert all(code == "1111010100" for code, _ in before.values())
    interim = await convert(evidence["interim"]["items"], evidence["new_token"])
    await load_bundles(session, interim, geo=context(evidence["new_token"]))
    partial = await rows()
    assert len(partial) == count
    completed_ids = {key for key, (code, _) in partial.items() if code == "1168010100"}
    assert len(completed_ids) == evidence["completed_before_recovery"]
    assert all(
        code == "1111010100"
        for key, (code, _) in partial.items()
        if key not in completed_ids
    )
    result = await load_bundles(session, new, geo=context(evidence["new_token"]))
    after = await rows()
    assert set(after) == set(before)
    assert all(code == "1168010100" for code, _ in after.values())
    assert all(after[k][1] > before[k][1] for k in before)
    assert result.source_records_inserted == count - len(interim)
    assert all(after[key] == partial[key] for key in completed_ids)
    repeated = await load_bundles(session, new, geo=context(evidence["new_token"]))
    assert repeated.source_records_inserted == 0
    assert await rows() == after

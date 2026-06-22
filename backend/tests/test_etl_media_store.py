"""media_store 버킷 매핑 회귀 테스트."""

from __future__ import annotations

from ktc.etl import media_store
from ktc.models import AssetType


def test_bucket_for_covers_all_asset_types():
    # 모든 AssetType이 버킷에 매핑되어야 한다. T-109에서 TRANSCRIPT_CORRECTED를
    # enum에만 추가하고 이 매핑을 빠뜨려 poi_batch 저장이 "알 수 없는 asset_type"으로
    # 실패했던 회귀를 막는다.
    for asset_type in AssetType:
        assert media_store.bucket_for(asset_type.value)


def test_transcript_corrected_shares_subtitle_bucket():
    assert media_store.bucket_for(
        AssetType.TRANSCRIPT_CORRECTED.value
    ) == media_store.bucket_for(AssetType.TRANSCRIPT.value)

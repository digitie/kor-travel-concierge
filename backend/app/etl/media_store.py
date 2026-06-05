"""RustFS 미디어 저장 + `media_assets` 기록.

자막·전사 결과·대표 프레임·원본 동영상을 S3 호환 RustFS에 업로드하고, DB에는
객체 URI·체크섬·크기만 기록한다. 보존 정책은 무기한이며 삭제 기능을 제공하지
않는다(`docs/architecture.md` 4.7, ADR-15).

저장 백엔드는 `MediaStore` 프로토콜로 추상화해, 테스트에서 in-memory 구현을
주입한다. 실제 RustFS 업로드는 `boto3` 기반 구현을 지연 import로 사용한다.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AssetType, MediaAsset

# asset_type -> 버킷 설정 키
_BUCKET_BY_ASSET_TYPE = {
    AssetType.RAW_VIDEO: "RUSTFS_BUCKET_RAW_VIDEOS",
    AssetType.SUBTITLE: "RUSTFS_BUCKET_SUBTITLES",
    AssetType.TRANSCRIPT: "RUSTFS_BUCKET_SUBTITLES",
    AssetType.FRAME: "RUSTFS_BUCKET_FRAMES",
}


def bucket_for(asset_type: str) -> str:
    """asset_type에 해당하는 RustFS 버킷 이름을 설정에서 조회한다."""
    settings = get_settings()
    key = _BUCKET_BY_ASSET_TYPE.get(AssetType(asset_type))
    if key is None:
        raise ValueError(f"알 수 없는 asset_type: {asset_type}")
    return getattr(settings, key)


@runtime_checkable
class MediaStore(Protocol):
    """객체 저장 백엔드 추상화."""

    def put_object(
        self, bucket: str, key: str, data: bytes, content_type: str | None
    ) -> str:
        """객체를 업로드하고 접근 URI를 반환한다."""
        ...


class InMemoryMediaStore:
    """테스트·드라이런용 in-memory 저장소."""

    def __init__(self, endpoint: str = "memory://rustfs"):
        self.endpoint = endpoint
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(
        self, bucket: str, key: str, data: bytes, content_type: str | None
    ) -> str:
        self.objects[(bucket, key)] = data
        return f"{self.endpoint}/{bucket}/{key}"


class RustFSMediaStore:
    """boto3 기반 RustFS(S3 호환) 저장소 (지연 import)."""

    def __init__(self) -> None:
        settings = get_settings()
        import boto3  # type: ignore

        self._endpoint = settings.RUSTFS_ENDPOINT
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.RUSTFS_ENDPOINT,
            aws_access_key_id=settings.RUSTFS_ACCESS_KEY,
            aws_secret_access_key=settings.RUSTFS_SECRET_KEY,
        )

    def put_object(
        self, bucket: str, key: str, data: bytes, content_type: str | None
    ) -> str:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=bucket, Key=key, Body=data, **extra)
        return f"{self._endpoint}/{bucket}/{key}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def store_and_record(
    session: AsyncSession,
    store: MediaStore,
    *,
    asset_type: str,
    object_key: str,
    data: bytes,
    content_type: str | None = None,
    video_id: str | None = None,
    place_id: int | None = None,
) -> MediaAsset:
    """객체를 업로드하고 `media_assets` 행을 기록한다."""
    bucket = bucket_for(asset_type)
    uri = store.put_object(bucket, object_key, data, content_type)
    asset = MediaAsset(
        asset_type=asset_type,
        video_id=video_id,
        place_id=place_id,
        storage_provider="rustfs",
        bucket=bucket,
        object_key=object_key,
        object_uri=uri,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256_hex(data),
        retention_policy=get_settings().MEDIA_RETENTION_POLICY,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset

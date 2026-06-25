"""RustFS 미디어 저장 + `media_assets` 기록.

자막·전사 결과·대표 프레임·원본 동영상을 S3 호환 RustFS에 업로드하고, DB에는
객체 URI·체크섬·크기만 기록한다. 보존 정책은 무기한이며 삭제 기능을 제공하지
않는다(`docs/architecture.md` 4.7, ADR-15).

저장 백엔드는 `MediaStore` 프로토콜로 추상화해, 테스트에서 in-memory 구현을
주입한다. 실제 RustFS 업로드는 `boto3` 기반 구현을 지연 import로 사용한다.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import BinaryIO, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.models import AssetType, MediaAsset

# asset_type -> 버킷 설정 키
_BUCKET_BY_ASSET_TYPE = {
    AssetType.RAW_VIDEO: "RUSTFS_BUCKET_RAW_VIDEOS",
    AssetType.SUBTITLE: "RUSTFS_BUCKET_SUBTITLES",
    AssetType.TRANSCRIPT: "RUSTFS_BUCKET_SUBTITLES",
    # 교정본도 자막 버킷에 저장한다(원본 TRANSCRIPT과 동일). T-109에서 enum만 추가하고
    # 이 매핑을 빠뜨려 poi_batch 저장 시 "알 수 없는 asset_type"으로 실패했었다.
    AssetType.TRANSCRIPT_CORRECTED: "RUSTFS_BUCKET_SUBTITLES",
    AssetType.FRAME: "RUSTFS_BUCKET_FRAMES",
}


def bucket_for(asset_type: str) -> str:
    """asset_type에 해당하는 RustFS 버킷 이름을 설정에서 조회한다."""
    settings = get_settings()
    key = _BUCKET_BY_ASSET_TYPE.get(AssetType(asset_type))
    if key is None:
        raise ValueError(f"알 수 없는 asset_type: {asset_type}")
    return getattr(settings, key)


def object_key_with_prefix(object_key: str) -> str:
    """전역 RustFS prefix를 객체 키 앞에 멱등하게 붙인다."""
    prefix = get_settings().RUSTFS_OBJECT_PREFIX.strip("/")
    clean_key = object_key.strip("/")
    if not prefix:
        return clean_key
    if clean_key == prefix or clean_key.startswith(f"{prefix}/"):
        return clean_key
    return f"{prefix}/{clean_key}"


@runtime_checkable
class MediaStore(Protocol):
    """객체 저장 백엔드 추상화."""

    def put_object(
        self, bucket: str, key: str, data: bytes, content_type: str | None
    ) -> str:
        """객체를 업로드하고 접근 URI를 반환한다."""
        ...

    def put_object_stream(
        self, bucket: str, key: str, fileobj: BinaryIO, content_type: str | None
    ) -> str:
        """file-like 객체를 업로드하고 접근 URI를 반환한다."""
        ...

    def get_object(self, bucket: str, key: str) -> bytes:
        """객체를 다운로드해 바이트로 반환한다(저장된 자막 재사용 등)."""
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

    def put_object_stream(
        self, bucket: str, key: str, fileobj: BinaryIO, content_type: str | None
    ) -> str:
        self.objects[(bucket, key)] = fileobj.read()
        return f"{self.endpoint}/{bucket}/{key}"

    def get_object(self, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]


class RustFSMediaStore:
    """boto3 기반 RustFS(S3 호환) 저장소 (지연 import)."""

    def __init__(self) -> None:
        settings = get_settings()
        import boto3  # type: ignore

        self._endpoint = settings.RUSTFS_ENDPOINT
        self._public_base_url = settings.RUSTFS_PUBLIC_BASE_URL.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.RUSTFS_ENDPOINT,
            aws_access_key_id=settings.RUSTFS_ACCESS_KEY,
            aws_secret_access_key=settings.RUSTFS_SECRET_KEY,
            region_name=settings.RUSTFS_REGION,
        )

    def put_object(
        self, bucket: str, key: str, data: bytes, content_type: str | None
    ) -> str:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=bucket, Key=key, Body=data, **extra)
        if self._public_base_url:
            return f"{self._public_base_url}/{key}"
        return f"{self._endpoint}/{bucket}/{key}"

    def put_object_stream(
        self, bucket: str, key: str, fileobj: BinaryIO, content_type: str | None
    ) -> str:
        from boto3.s3.transfer import TransferConfig  # type: ignore

        upload_kwargs = (
            {"ExtraArgs": {"ContentType": content_type}} if content_type else {}
        )
        self._client.upload_fileobj(
            fileobj,
            bucket,
            key,
            Config=TransferConfig(use_threads=False),
            **upload_kwargs,
        )
        if self._public_base_url:
            return f"{self._public_base_url}/{key}"
        return f"{self._endpoint}/{bucket}/{key}"

    def get_object(self, bucket: str, key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()


class HashingReader:
    """업로드 스트림을 읽으면서 SHA256과 byte 수를 계산한다."""

    def __init__(self, fileobj: BinaryIO):
        self._fileobj = fileobj
        self._hash = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._fileobj.read(size)
        if not chunk:
            return b""
        self._hash.update(chunk)
        self.bytes_read += len(chunk)
        return chunk

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()


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
    stored_object_key = object_key_with_prefix(object_key)
    existing_result = await session.execute(
        select(MediaAsset).where(
            MediaAsset.bucket == bucket,
            MediaAsset.object_key == stored_object_key,
        )
    )
    existing = existing_result.scalars().first()
    if existing is not None:
        return existing

    uri = await asyncio.to_thread(
        store.put_object, bucket, stored_object_key, data, content_type
    )
    asset = MediaAsset(
        asset_type=asset_type,
        video_id=video_id,
        place_id=place_id,
        storage_provider="rustfs",
        bucket=bucket,
        object_key=stored_object_key,
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


async def load_latest_asset(
    session: AsyncSession,
    *,
    video_id: str,
    asset_type: str,
) -> MediaAsset | None:
    """영상의 특정 asset_type 중 가장 최근 `media_assets` 행을 반환한다."""
    result = await session.execute(
        select(MediaAsset)
        .where(
            MediaAsset.video_id == video_id,
            MediaAsset.asset_type == asset_type,
        )
        .order_by(MediaAsset.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def load_latest_asset_text(
    session: AsyncSession,
    store: MediaStore,
    *,
    video_id: str,
    asset_type: str,
) -> str | None:
    """저장된 자막/교정본 텍스트를 다시 읽어 반환한다(단계별 재처리 재사용용).

    해당 asset이 없으면 None. RustFS 다운로드는 blocking이라 thread로 offload한다.
    """
    asset = await load_latest_asset(session, video_id=video_id, asset_type=asset_type)
    if asset is None:
        return None
    data = await asyncio.to_thread(store.get_object, asset.bucket, asset.object_key)
    return data.decode("utf-8")


async def store_stream_and_record(
    session: AsyncSession,
    store: MediaStore,
    *,
    asset_type: str,
    object_key: str,
    fileobj: BinaryIO,
    content_type: str | None = None,
    video_id: str | None = None,
    place_id: int | None = None,
) -> MediaAsset:
    """file-like 객체를 업로드하고 `media_assets` 행을 기록한다.

    원본 동영상처럼 큰 객체는 이 경로를 사용해 전체 파일을 `bytes`로 만들지 않고
    RustFS multipart 업로드에 넘긴다. 업로드 중 읽은 chunk로 checksum과 크기를
    계산한다.
    """
    bucket = bucket_for(asset_type)
    stored_object_key = object_key_with_prefix(object_key)
    existing_result = await session.execute(
        select(MediaAsset).where(
            MediaAsset.bucket == bucket,
            MediaAsset.object_key == stored_object_key,
        )
    )
    existing = existing_result.scalars().first()
    if existing is not None:
        return existing

    hashing_reader = HashingReader(fileobj)
    uri = await asyncio.to_thread(
        store.put_object_stream,
        bucket,
        stored_object_key,
        hashing_reader,
        content_type,
    )
    asset = MediaAsset(
        asset_type=asset_type,
        video_id=video_id,
        place_id=place_id,
        storage_provider="rustfs",
        bucket=bucket,
        object_key=stored_object_key,
        object_uri=uri,
        content_type=content_type,
        size_bytes=hashing_reader.bytes_read,
        sha256=hashing_reader.sha256,
        retention_policy=get_settings().MEDIA_RETENTION_POLICY,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset

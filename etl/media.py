"""RustFS 미디어 저장 계층 (스캐폴드).

원본 동영상, 자막, 전사 결과, 대표 프레임을 S3 호환 RustFS에 업로드하고,
객체 URI·체크섬·크기·보존 정책 메타데이터를 반환한다. DB(`media_assets`)에는
이 메타데이터만 기록하고 대용량 바이너리는 저장하지 않는다.
(`docs/architecture.md` 4.7, ADR-15)

보존 정책은 무기한이며, 이 모듈은 객체 삭제 기능을 제공하지 않는다.
(`AGENTS.md` DO NOT 6: RustFS 객체 자동 삭제 금지)
"""

import hashlib
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


# asset_type -> (버킷 환경 변수, 기본 버킷명) 매핑
_BUCKET_ENV_BY_ASSET_TYPE = {
    "raw_video": ("RUSTFS_BUCKET_RAW_VIDEOS", "krtour-map"),
    "subtitle": ("RUSTFS_BUCKET_SUBTITLES", "krtour-map"),
    "transcript": ("RUSTFS_BUCKET_SUBTITLES", "krtour-map"),
    "frame": ("RUSTFS_BUCKET_FRAMES", "krtour-map"),
}


@dataclass
class StoredMediaAsset:
    """RustFS 업로드 결과 메타데이터. `media_assets` 행으로 적재된다."""

    asset_type: str
    storage_provider: str
    bucket: str
    object_key: str
    object_uri: str
    size_bytes: int
    sha256: str
    content_type: str | None = None
    retention_policy: str = "infinite"


def _bucket_for(asset_type: str) -> str:
    mapping = _BUCKET_ENV_BY_ASSET_TYPE.get(asset_type)
    if mapping is None:
        raise ValueError(f"알 수 없는 asset_type: {asset_type}")
    env_name, default_bucket = mapping
    return os.getenv(env_name, default_bucket)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_key_with_prefix(object_key: str) -> str:
    prefix = os.getenv("RUSTFS_OBJECT_PREFIX", "features").strip("/")
    clean_key = object_key.strip("/")
    if not prefix:
        return clean_key
    if clean_key == prefix or clean_key.startswith(f"{prefix}/"):
        return clean_key
    return f"{prefix}/{clean_key}"


def store_media_asset(
    asset_type: str,
    object_key: str,
    data: bytes,
    content_type: str | None = None,
) -> StoredMediaAsset:
    """미디어 객체를 RustFS에 업로드하고 메타데이터를 반환한다.

    Placeholder: 실제 업로드는 T-007/T-009에서 `boto3`/`aioboto3` S3 클라이언트로
    구현한다. 현재는 버킷 라우팅, 체크섬, URI 조립 계약만 고정한다.
    """
    endpoint = os.getenv("RUSTFS_ENDPOINT", "http://127.0.0.1:9003")
    public_base_url = os.getenv(
        "RUSTFS_PUBLIC_BASE_URL", "http://127.0.0.1:9003/krtour-map"
    ).rstrip("/")
    bucket = _bucket_for(asset_type)
    stored_object_key = _object_key_with_prefix(object_key)
    checksum = _sha256(data)

    print(
        f"[RustFS Log] {asset_type} 객체 업로드 예정: "
        f"bucket={bucket} key={stored_object_key} size={len(data)}B"
    )

    # Placeholder: S3 PutObject 호출 위치
    return StoredMediaAsset(
        asset_type=asset_type,
        storage_provider="rustfs",
        bucket=bucket,
        object_key=stored_object_key,
        object_uri=(
            f"{public_base_url}/{stored_object_key}"
            if public_base_url
            else f"{endpoint}/{bucket}/{stored_object_key}"
        ),
        size_bytes=len(data),
        sha256=checksum,
        content_type=content_type,
        retention_policy=os.getenv("MEDIA_RETENTION_POLICY", "infinite"),
    )


if __name__ == "__main__":
    sample = store_media_asset(
        "frame", "video_999/frame_00_03_30.jpg", b"\xff\xd8\xff", "image/jpeg"
    )
    print(f"저장 결과: {sample}")

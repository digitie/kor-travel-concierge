"""RustFS 버킷과 객체 저장 smoke 검증.

Docker Compose의 `api` 컨테이너 안에서 실행하는 것을 기본 전제로 한다.
`RUSTFS_ENDPOINT`, `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`, 기본 버킷 환경 변수를
읽어 버킷 생성, 객체 업로드, 객체 조회를 확인한다. 무기한 보존 원칙에 따라
검증 객체는 삭제하지 않고 같은 key로 덮어쓴다.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} 환경 변수가 비어 있다")
    return value


def _ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status not in (403, 404):
            raise
        client.create_bucket(Bucket=bucket)


def main() -> int:
    endpoint = _required_env("RUSTFS_ENDPOINT")
    access_key = _required_env("RUSTFS_ACCESS_KEY")
    secret_key = _required_env("RUSTFS_SECRET_KEY")
    buckets = [
        _required_env("RUSTFS_BUCKET_RAW_VIDEOS"),
        _required_env("RUSTFS_BUCKET_SUBTITLES"),
        _required_env("RUSTFS_BUCKET_FRAMES"),
    ]

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )

    body = f"tripmate-agent rustfs smoke {datetime.now(UTC).isoformat()}\n".encode()
    key = "healthcheck/t014-smoke.txt"
    for bucket in buckets:
        _ensure_bucket(client, bucket)
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="text/plain")
        head = client.head_object(Bucket=bucket, Key=key)
        size = int(head.get("ContentLength", 0))
        if size != len(body):
            raise RuntimeError(f"{bucket}/{key} 크기 불일치: {size} != {len(body)}")
        print(f"OK {bucket}/{key} {size} bytes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RustFS smoke 검증 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)

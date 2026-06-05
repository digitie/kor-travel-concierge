"""RustFS 초기 버킷 생성 스크립트 (T-003).

`.env`의 RustFS 설정을 읽어 다음 버킷을 멱등하게 생성한다.
    - tripmate-raw-videos : 원본 동영상/오디오
    - tripmate-subtitles  : 자막·자동자막·전사 결과
    - tripmate-frames     : 대표 프레임 JPEG

버킷은 무기한 보존이며 lifecycle 만료 정책을 설정하지 않는다(ADR-15).

실행:
    python scripts/init_rustfs_buckets.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    endpoint = os.getenv("RUSTFS_ENDPOINT", "http://localhost:9003")
    access_key = os.getenv("RUSTFS_ACCESS_KEY", "")
    secret_key = os.getenv("RUSTFS_SECRET_KEY", "")
    buckets = [
        os.getenv("RUSTFS_BUCKET_RAW_VIDEOS", "tripmate-raw-videos"),
        os.getenv("RUSTFS_BUCKET_SUBTITLES", "tripmate-subtitles"),
        os.getenv("RUSTFS_BUCKET_FRAMES", "tripmate-frames"),
    ]

    if not access_key or not secret_key:
        print("[init] RUSTFS_ACCESS_KEY / RUSTFS_SECRET_KEY 미설정. .env를 확인하라.")
        return 1

    try:
        import boto3  # type: ignore
    except ImportError:
        print("[init] boto3 미설치. `pip install -r etl/requirements.txt` 후 재실행.")
        return 1

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    for bucket in buckets:
        if bucket in existing:
            print(f"[init] 버킷 존재: {bucket}")
            continue
        s3.create_bucket(Bucket=bucket)
        print(f"[init] 버킷 생성: {bucket}")

    print("[init] RustFS 버킷 초기화 완료 (보존 정책: 무기한)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""기존 확정 장소의 kor-travel-geo v2 행정코드 백필."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import or_, select

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from ktc.core.database import async_session_factory  # noqa: E402
from ktc.etl.admin_region_service import enrich_place_admin_codes  # noqa: E402
from ktc.models import TravelPlace  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="travel_places의 비어 있는 법정동/시군구 코드를 채웁니다."
    )
    parser.add_argument("--limit", type=int, default=0, help="0이면 제한 없음")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    batch_size = max(1, args.batch_size)
    async with async_session_factory() as session:
        stmt = (
            select(TravelPlace)
            .where(
                TravelPlace.is_geocoded.is_(True),
                TravelPlace.latitude.isnot(None),
                TravelPlace.longitude.isnot(None),
                or_(
                    TravelPlace.sigungu_code.is_(None),
                    TravelPlace.legal_dong_code.is_(None),
                ),
            )
            .order_by(TravelPlace.place_id.asc())
        )
        if args.limit > 0:
            stmt = stmt.limit(args.limit)
        places = list((await session.execute(stmt)).scalars().all())
        updated = 0
        failed_or_skipped = 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for index, place in enumerate(places, start=1):
                changed = await enrich_place_admin_codes(
                    session,
                    place,
                    http_client=client,
                )
                if changed:
                    updated += 1
                else:
                    failed_or_skipped += 1
                if not args.dry_run and index % batch_size == 0:
                    await session.commit()
        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()
    print(
        "admin_code_backfill "
        f"scanned={len(places)} updated={updated} skipped_or_failed={failed_or_skipped} "
        f"dry_run={int(args.dry_run)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))

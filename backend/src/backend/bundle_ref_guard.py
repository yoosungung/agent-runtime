from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.bucket_paths import sha256_from_key
from runtime_common.db.models import SourceMetaRow


async def ref_count_for_sha256(db: AsyncSession, sha256_hex: str) -> int:
    checksum = f"sha256:{sha256_hex}"
    result = await db.execute(
        select(func.count())
        .select_from(SourceMetaRow)
        .where(SourceMetaRow.checksum == checksum)
    )
    return int(result.scalar_one())


async def ref_counts_for_keys(db: AsyncSession, keys: list[str]) -> dict[str, int]:
    """Return ref_count per key (0 for non-bundle keys)."""
    counts: dict[str, int] = {}
    cache: dict[str, int] = {}
    for key in keys:
        sha = sha256_from_key(key)
        if sha is None:
            counts[key] = 0
            continue
        if sha not in cache:
            cache[sha] = await ref_count_for_sha256(db, sha)
        counts[key] = cache[sha]
    return counts


async def assert_keys_not_in_use(db: AsyncSession, keys: list[str]) -> None:
    """Raise 409 if any bundle key is referenced by source_meta."""
    in_use: list[str] = []
    for key in keys:
        sha = sha256_from_key(key)
        if sha is None:
            continue
        if await ref_count_for_sha256(db, sha) > 0:
            in_use.append(key)
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                "Object(s) referenced by Source Meta cannot be deleted or moved: "
                + ", ".join(sorted(in_use))
            ),
        )

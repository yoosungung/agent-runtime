#!/usr/bin/env python3
"""CLI for purging soft-deleted chat thread provider data.

Usage:
  POSTGRES_DSN=postgresql+asyncpg://... uv run python scripts/purge_deleted_chat_threads.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from runtime_common.chat_threads_purge import purge_deleted_threads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days",
        type=int,
        default=int(os.environ.get("CHAT_THREAD_PURGE_RETENTION_DAYS", "30")),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hard-delete", action="store_true")
    args = parser.parse_args()

    dsn = os.environ.get("POSTGRES_DSN", "")
    if not dsn:
        raise SystemExit("POSTGRES_DSN is required")

    logging.basicConfig(level=logging.INFO)
    count = asyncio.run(
        purge_deleted_threads(
            dsn=dsn,
            retention_days=args.retention_days,
            dry_run=args.dry_run,
            hard_delete=args.hard_delete,
        )
    )
    logging.info("purged %s thread(s)", count)


if __name__ == "__main__":
    main()

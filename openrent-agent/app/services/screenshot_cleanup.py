"""
Periodic background task: prune old screenshots so they cannot fill the disk.

Browser workers write diagnostic and per-thread screenshots under screenshots/
and nothing ever cleans them up; left unbounded they grow ~2GB/day and on
2026-08-11 they filled the root disk to 100%, which crashed every headless
browser (renderer "Page crashed" on zero free disk). This service deletes
screenshot files older than a retention window and removes the now-empty
per-thread folders. It is filesystem-only and hard-scoped to screenshots/.

Tunables (env, no code change needed):
- SCREENSHOT_RETENTION_DAYS         (default 7)
- SCREENSHOT_CLEANUP_INTERVAL_HOURS (default 6)
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from pathlib import Path

from app.utils.logger import logger

_RETENTION_DAYS = int(os.getenv("SCREENSHOT_RETENTION_DAYS", "7"))
_INTERVAL_SECONDS = int(os.getenv("SCREENSHOT_CLEANUP_INTERVAL_HOURS", "6")) * 60 * 60


def _prune_old_screenshots(retention_days: int) -> tuple[int, int]:
    """Delete screenshot files older than retention_days and remove empty
    per-thread folders. Returns (files_deleted, bytes_freed). A single-file
    error is logged and skipped, never raised."""
    # Resolve relative to CWD exactly like the writers (auth.py / api/main.py
    # both use Path("screenshots")). Backend runs with WorkingDirectory set to
    # the app root, so this points at the real screenshots directory.
    root = Path("screenshots").resolve()
    if not root.exists():
        return (0, 0)

    cutoff = time.time() - retention_days * 24 * 60 * 60
    files_deleted = 0
    bytes_freed = 0

    for dirpath, _dirnames, filenames in os.walk(root):
        # Safety: never touch anything outside the screenshots root.
        try:
            Path(dirpath).resolve().relative_to(root)
        except ValueError:
            continue
        for name in filenames:
            fpath = os.path.join(dirpath, name)
            try:
                st = os.stat(fpath)
                if st.st_mtime < cutoff:
                    size = st.st_size
                    os.remove(fpath)
                    files_deleted += 1
                    bytes_freed += size
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning(f"SCREENSHOT_CLEANUP_UNLINK_FAILED path={fpath} error={exc}")

    # Remove empty per-thread directories bottom-up; keep the screenshots/ and
    # screenshots/threads/ roots themselves.
    threads_root = root / "threads"
    if threads_root.exists():
        for dirpath, _dirnames, _filenames in os.walk(threads_root, topdown=False):
            dpath = Path(dirpath)
            if dpath == threads_root:
                continue
            try:
                if not any(dpath.iterdir()):
                    dpath.rmdir()
            except OSError:
                continue

    return (files_deleted, bytes_freed)


async def _run_cleanup() -> None:
    files_deleted, bytes_freed = await asyncio.to_thread(
        _prune_old_screenshots, _RETENTION_DAYS
    )
    if files_deleted:
        logger.info(
            f"SCREENSHOT_CLEANUP_CYCLE deleted={files_deleted} "
            f"freed_mb={bytes_freed / 1024 / 1024:.1f} retention_days={_RETENTION_DAYS}"
        )


async def _screenshot_cleanup_loop() -> None:
    # Small initial delay so the app finishes starting up first.
    await asyncio.sleep(90)
    while True:
        try:
            await _run_cleanup()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"SCREENSHOT_CLEANUP_FAILED error={exc}")
        await asyncio.sleep(_INTERVAL_SECONDS)


def start_screenshot_cleanup() -> asyncio.Task:
    logger.info(
        f"SCREENSHOT_CLEANUP_STARTED interval_hours={_INTERVAL_SECONDS // 3600} "
        f"retention_days={_RETENTION_DAYS}"
    )
    return asyncio.create_task(_screenshot_cleanup_loop(), name="screenshot-cleanup")


async def stop_screenshot_cleanup(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

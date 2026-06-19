from datetime import datetime, timedelta

from app.config import settings
from app.db.repository import (
    get_sheet_export_payload,
    mark_sheet_export_failed,
    mark_sheet_export_succeeded,
    save_listing_metadata,
)
from app.integrations.google_sheets import (
    GoogleSheetsConfigurationError,
    GoogleSheetsStructureError,
    configured_exporter,
)
from app.utils.logger import logger


RETRY_DELAYS_MINUTES = (1, 5, 15, 60, 180, 360, 720, 1440)
METADATA_FIELDS = ("landlord_name", "address", "bedrooms", "bathrooms", "rent_pcm")


def _http_error_details(exc):
    status = getattr(getattr(exc, "resp", None), "status", None)
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    return status, str(content or "")


def _is_retryable(exc):
    if isinstance(exc, GoogleSheetsStructureError):
        return False
    if isinstance(exc, GoogleSheetsConfigurationError):
        return True

    status, content = _http_error_details(exc)
    if status in {408, 429, 500, 502, 503, 504}:
        return True
    if status == 403 and any(
        marker in content
        for marker in ("rateLimitExceeded", "userRateLimitExceeded", "backendError")
    ):
        return True
    if status in {400, 401, 403, 404}:
        return False

    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def _hydrate_missing_metadata(payload):
    missing = [field for field in METADATA_FIELDS if payload.get(field) is None]
    if not missing:
        return payload

    from app.openrent.listing_metadata import fetch_listing_metadata

    logger.info(
        "GOOGLE_SHEETS_METADATA_HYDRATION_START "
        f"export_id={payload.get('export_id')} listing_id={payload.get('listing_id')} "
        f"missing_fields={','.join(missing)}"
    )
    try:
        metadata = fetch_listing_metadata(payload["property_url"])
        save_listing_metadata(payload["listing_pk"], metadata)
        refreshed = get_sheet_export_payload(payload["export_id"])
        remaining = [
            field for field in METADATA_FIELDS if refreshed.get(field) is None
        ]
        logger.info(
            "GOOGLE_SHEETS_METADATA_HYDRATION_SUCCESS "
            f"export_id={payload.get('export_id')} listing_id={payload.get('listing_id')} "
            f"remaining_fields={','.join(remaining) if remaining else 'none'}"
        )
        return refreshed
    except Exception as exc:
        # Phone and URL are still sufficient for an export. Keep the export
        # moving, but make the metadata failure explicit in logs.
        logger.exception(
            "GOOGLE_SHEETS_METADATA_HYDRATION_FAILED "
            f"export_id={payload.get('export_id')} listing_id={payload.get('listing_id')} "
            f"missing_fields={','.join(missing)} error_type={type(exc).__name__}"
        )
        return payload


def run_lead_sheet_export_sync(export_id):
    payload = get_sheet_export_payload(export_id)
    if not payload:
        logger.error(
            f"GOOGLE_SHEETS_EXPORT_MISSING export_id={export_id}"
        )
        return {"exported": False, "reason": "missing_export"}
    if payload.get("current_status") == "EXPORTED":
        logger.info(
            "GOOGLE_SHEETS_EXPORT_ALREADY_COMPLETE "
            f"export_id={export_id} listing_id={payload.get('listing_id')}"
        )
        return {"exported": True, "reason": "already_exported"}

    try:
        payload = _hydrate_missing_metadata(payload)
        from app.queue.redis_conn import redis_conn

        lock = redis_conn.lock(
            f"google-sheets:{settings.GOOGLE_SHEET_ID}",
            timeout=300,
            blocking_timeout=30,
        )
        if not lock.acquire(blocking=True):
            raise TimeoutError("Timed out waiting for Google Sheets export lock")
        try:
            exporter = configured_exporter()
            result = exporter.export(payload)
        finally:
            try:
                lock.release()
            except Exception:
                logger.warning(
                    f"GOOGLE_SHEETS_LOCK_RELEASE_FAILED export_id={export_id}"
                )
        mark_sheet_export_succeeded(
            export_id,
            destination_tab=result["tab"],
            destination_row=result["row"],
            payload_hash=result["payload_hash"],
        )
        return {"exported": True, **result}
    except Exception as exc:
        retryable = _is_retryable(exc)
        attempt_number = (payload.get("attempt_count") or 0) + 1
        exhausted = attempt_number >= settings.GOOGLE_SHEETS_MAX_ATTEMPTS
        permanent = not retryable or exhausted
        delay_index = min(attempt_number - 1, len(RETRY_DELAYS_MINUTES) - 1)
        next_attempt_at = (
            None
            if permanent
            else datetime.utcnow()
            + timedelta(minutes=RETRY_DELAYS_MINUTES[delay_index])
        )
        status, _ = _http_error_details(exc)

        mark_sheet_export_failed(
            export_id,
            error=exc,
            next_attempt_at=next_attempt_at,
            permanent=permanent,
        )
        logger.exception(
            "GOOGLE_SHEETS_EXPORT_FAILED "
            f"export_id={export_id} conversation_id={payload.get('conversation_id')} "
            f"thread_id={payload.get('thread_id')} listing_id={payload.get('listing_id')} "
            f"attempt={attempt_number} retryable={retryable} exhausted={exhausted} "
            f"permanent={permanent} http_status={status} "
            f"next_attempt_at={next_attempt_at} error_type={type(exc).__name__}"
        )
        return {
            "exported": False,
            "permanent": permanent,
            "retryable": retryable,
            "next_attempt_at": next_attempt_at,
            "error": str(exc),
        }

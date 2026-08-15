"""Gate for when AI viewing-detection runs.

Regression for the no-show root cause (2026-08-15): detection was skipped
whenever a "Request Viewing" banner was present, so landlord bookings confirmed
in free-text chat were never detected -> viewing_confirmed stayed False -> the
3-5h cancellation strategy never fired -> the AI stalled and no-showed. It must
now run whenever the viewing is not already confirmed, including when a request
banner is present.
"""
from scripts.process_replies import _should_run_viewing_detection


def _banners(confirmed=False, requested=False):
    return {
        "viewing_confirmed": confirmed,
        "viewing_requested": requested,
        "viewing_datetime": None,
    }


def test_runs_when_request_banner_present():
    # THE FIX: previously this returned False and blocked detection forever.
    assert _should_run_viewing_detection(_banners(confirmed=False, requested=True)) is True


def test_runs_when_no_banner():
    assert _should_run_viewing_detection(_banners(confirmed=False, requested=False)) is True


def test_skips_when_already_confirmed():
    assert _should_run_viewing_detection(_banners(confirmed=True, requested=True)) is False
    assert _should_run_viewing_detection(_banners(confirmed=True, requested=False)) is False

"""Gate for when AI viewing-detection runs.

Regression for the no-show root cause (2026-08-15): detection was skipped
whenever a "Request Viewing" banner was present, so landlord bookings confirmed
in free-text chat were never detected -> viewing_confirmed stayed False -> the
3-5h cancellation strategy never fired -> the AI stalled and no-showed. It must
now run whenever the viewing is not already confirmed, including when a request
banner is present.
"""
from types import SimpleNamespace

from scripts.process_replies import (
    _should_run_viewing_detection,
    HANDOFF_COMPLETE,
    VIEWING_CANCELLED,
    SHORT_TERM_PROPERTY,
)


def _banners(confirmed=False, requested=False):
    return {
        "viewing_confirmed": confirmed,
        "viewing_requested": requested,
        "viewing_datetime": None,
    }


def _conv(stage=None, viewing_confirmed=False):
    return SimpleNamespace(
        conversation_stage=stage,
        viewing_confirmed=viewing_confirmed,
    )


def test_runs_when_request_banner_present():
    # THE FIX: previously this returned False and blocked detection forever.
    assert _should_run_viewing_detection(_banners(confirmed=False, requested=True)) is True


def test_runs_when_no_banner():
    assert _should_run_viewing_detection(_banners(confirmed=False, requested=False)) is True


def test_skips_when_already_confirmed():
    assert _should_run_viewing_detection(_banners(confirmed=True, requested=True)) is False
    assert _should_run_viewing_detection(_banners(confirmed=True, requested=False)) is False


# --- Cost guards (2026-08-25 audit): stop re-scanning unchanged conversations ---
# The detector ran on every worker pass for chat-confirmed viewings (no live
# banner), re-scanning identical text ~18x/day. These guards must remove ONLY
# the redundant re-runs, never a real detection.


def test_skips_when_no_new_landlord_message():
    # The redundant re-run: banner never confirmed, but the landlord has said
    # nothing new since we last processed. Same input -> identical result the DB
    # already holds. This single guard removes the bulk of the ~6,377 calls/day.
    assert _should_run_viewing_detection(
        _banners(confirmed=False),
        conversation=_conv(stage="VIEWING_DISCUSSION"),
        has_new_landlord_message=False,
    ) is False


def test_runs_when_new_landlord_message_and_unconfirmed():
    # A genuinely new landlord message on an unconfirmed thread: a booking may
    # have just been agreed -> the detector must still run.
    assert _should_run_viewing_detection(
        _banners(confirmed=False),
        conversation=_conv(stage="VIEWING_DISCUSSION"),
        has_new_landlord_message=True,
    ) is True


def test_reschedule_of_confirmed_viewing_still_runs():
    # RESCHEDULE PRESERVATION (the case that must NOT regress): the viewing was
    # already confirmed and persisted in the DB, but the landlord has now sent a
    # NEW message moving the time. The live banner is absent (chat-confirmed), so
    # banners["viewing_confirmed"] is False. Because there IS a new landlord
    # message and the thread is not terminal, the detector still runs and
    # re-resolves viewing_datetime — exactly as before the guards. If this ever
    # returns False, a rescheduled viewing would keep its stale time and the
    # cancel flow would fire against the wrong moment.
    assert _should_run_viewing_detection(
        _banners(confirmed=False),
        conversation=_conv(stage="VIEWING_BOOKED", viewing_confirmed=True),
        has_new_landlord_message=True,
    ) is True


def test_skips_terminal_stages_even_with_new_message():
    # Terminal threads send no reply and their viewing state is final; detecting
    # a booking on them changes nothing, so skip even on a new landlord message.
    for stage in (HANDOFF_COMPLETE, VIEWING_CANCELLED, SHORT_TERM_PROPERTY):
        assert _should_run_viewing_detection(
            _banners(confirmed=False),
            conversation=_conv(stage=stage),
            has_new_landlord_message=True,
        ) is False


def test_single_arg_call_is_backward_compatible():
    # Existing callers passing only `banners` keep the original behaviour.
    assert _should_run_viewing_detection(_banners(confirmed=False)) is True
    assert _should_run_viewing_detection(_banners(confirmed=True)) is False

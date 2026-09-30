"""Our own messages on live OpenRent threads are labelled sender="us"
(app/openrent/inbox.py extract_conversation). Every "sent by us" check must
recognise that label, or the give-out and already-shared logic never fires.
"""
from app.ai.conversation_memory import outbound_count, phone_shared_state
from app.ai.personas import TENANT_SENDERS, tenant_shared_phone
from app.ai.replies import count_number_asks

MOBILE = "07783129181"


def _live_thread():
    # Exact shape produced by inbox.extract_conversation.
    return [
        {"sender": "us", "message": "Hi, is the flat still available? We'd love to view it."},
        {"sender": "landlord", "message": "Yes it is. When are you free?"},
        {"sender": "us", "message": "Saturday works. Could I get your number just in case we're delayed?"},
        {"sender": "landlord", "message": "I'd rather keep it on here. What's your number?"},
    ]


def test_us_is_a_tenant_sender():
    assert "us" in TENANT_SENDERS
    assert "landlord" not in TENANT_SENDERS
    assert "inbound" not in TENANT_SENDERS


def test_count_number_asks_counts_live_us_messages():
    assert count_number_asks(_live_thread()) == 1


def test_count_number_asks_ignores_landlord_asks():
    msgs = [{"sender": "landlord", "message": "what's your number?"}]
    assert count_number_asks(msgs) == 0


def test_outbound_count_counts_live_us_messages():
    assert outbound_count(_live_thread()) == 2


def test_db_rows_still_counted():
    rows = [
        {"direction": "outbound", "content": "Could I get your number please?"},
        {"direction": "inbound", "content": "sure"},
    ]
    assert count_number_asks(rows) == 1
    assert outbound_count(rows) == 1


def test_tenant_shared_phone_detects_live_us_message_any_format():
    for written in ("07783129181", "07783 129181", "+44 7783 129181", "07783-129-181"):
        msgs = [{"sender": "us", "message": f"My husband's WhatsApp is {written}"}]
        assert tenant_shared_phone(msgs, MOBILE), written


def test_tenant_shared_phone_ignores_landlord_quoting_digits():
    msgs = [{"sender": "landlord", "message": "is 07783129181 your number?"}]
    assert not tenant_shared_phone(msgs, MOBILE)


def test_phone_shared_state_uses_live_messages():
    msgs = _live_thread() + [{"sender": "us", "message": "My husband's WhatsApp is 07783 129181"}]
    assert phone_shared_state(msgs, {"mobile_number": MOBILE}) is True
    assert phone_shared_state(_live_thread(), {"mobile_number": MOBILE}) is False


# --- remove_unapproved_phone_numbers: our own number survives in any format ---
from app.ai.validators import remove_unapproved_phone_numbers  # noqa: E402


def test_validator_keeps_our_number_written_as_plus44():
    out = remove_unapproved_phone_numbers("My husband's WhatsApp is +44 7783 129181.", MOBILE)
    assert "7783 129181" in out


def test_validator_keeps_our_number_written_nationally():
    out = remove_unapproved_phone_numbers("It's 07783 129181, thanks", "+447783129181")
    assert "07783 129181" in out


def test_validator_still_strips_other_numbers():
    out = remove_unapproved_phone_numbers("Call 07911 123456 or 07783129181", MOBILE)
    assert "07911" not in out and "07783129181" in out

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.ai.prompts import build_reply_prompt
from app.ai.replies import generate_reply
from app.experiments import playbook_ab
from scripts import process_replies


MOBILE = "+447743722832"
PERSONA = {
    "persona_name": "Mary",
    "mobile_number": MOBILE,
    "phone_fetching_type": "immediate",
    "conversation_style": "warm_casual",
    "persona_type": "young_professional_couple",
    "persona_partner_name": "Alex",
}


class DummyAccount:
    id = 1
    email = "mary@example.test"


def _conversation_stub():
    return SimpleNamespace(
        conversation_stage=None,
        status=None,
        last_processed_message=None,
        follow_up_count=0,
        landlord_attitude=None,
        conversation_style=None,
        viewing_datetime=None,
        viewing_cancelled=False,
        handoff_completed_at=None,
        extracted_phone=None,
        phone_requested_at=None,
        last_outbound_at=None,
        created_at=datetime.utcnow(),
    )


def _patch_process_flow(
    monkeypatch, latest_message, log_path, sent_replies, expect_assignment=True
):
    messages = [
        {
            "sender": "landlord",
            "message": latest_message,
            "timestamp": "2026-06-17T10:00:00+00:00",
        }
    ]
    conversation = _conversation_stub()

    async def get_threads(_page):
        return [{"thread_id": "thread-shortcut"}]

    async def noop_async(*_args, **_kwargs):
        return None

    async def extract_conversation(_page):
        return messages

    async def extract_banners(_page):
        return {
            "viewing_confirmed": False,
            "viewing_requested": False,
            "viewing_datetime": None,
        }

    async def can_reply(_page):
        return True

    async def reveal_hidden_phone_number(_page):
        return False

    async def send_reply(_page, reply):
        assert log_path.exists() is expect_assignment
        sent_replies.append(reply)
        return True

    monkeypatch.setenv("PLAYBOOK_AB_LOG", str(log_path))
    monkeypatch.setattr(process_replies, "get_all_reply_threads", get_threads)
    monkeypatch.setattr(process_replies, "account_stop_requested", lambda _id: False)
    monkeypatch.setattr(process_replies, "claim_conversation", lambda *_args: True)
    monkeypatch.setattr(process_replies, "open_thread", noop_async)
    monkeypatch.setattr(process_replies, "extract_conversation", extract_conversation)
    monkeypatch.setattr(process_replies, "extract_thread_banners", extract_banners)
    monkeypatch.setattr(process_replies, "save_banner_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(process_replies, "save_inbound_messages", lambda *_args: None)
    monkeypatch.setattr(process_replies, "get_conversation_by_thread_id", lambda _thread_id: conversation)
    monkeypatch.setattr(
        process_replies,
        "get_playbook_ab_enrollment_state",
        lambda _thread_id: {
            "outbound_count": 1,
            "inbound_count": 1,
            "message_contents": ["Initial enquiry", latest_message],
            "phone_found": False,
            "extracted_phone": None,
            "phone_found_at": None,
            "phone_requested_at": None,
            "last_ai_reply": None,
        },
    )
    monkeypatch.setattr(process_replies, "get_latest_landlord_message", lambda _messages: latest_message)
    monkeypatch.setattr(process_replies, "_screenshot_thread", noop_async)
    monkeypatch.setattr(process_replies, "should_ai_reply", lambda _messages: True)
    monkeypatch.setattr(process_replies, "can_reply", can_reply)
    monkeypatch.setattr(process_replies, "get_landlord_messages", lambda _messages: latest_message)
    monkeypatch.setattr(process_replies, "ensure_account_persona", lambda _account_id: PERSONA)
    monkeypatch.setattr(process_replies, "detect_landlord_attitude", lambda *_args, **_kwargs: "responsive")
    monkeypatch.setattr(process_replies, "latest_landlord_asked_for_phone", lambda _messages: False)
    monkeypatch.setattr(process_replies, "update_conversation_memory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(process_replies, "close_verified_tenant_popup", noop_async)
    monkeypatch.setattr(process_replies, "regex_extract_phone", lambda _texts: None)
    monkeypatch.setattr(process_replies, "reveal_hidden_phone_number", reveal_hidden_phone_number)
    monkeypatch.setattr(process_replies, "ai_extract_phone", lambda _texts: None)
    monkeypatch.setattr(process_replies, "detect_stage", lambda _messages: None)
    monkeypatch.setattr(process_replies, "get_thread_property_location", lambda _thread_id: None)
    monkeypatch.setattr(process_replies, "get_travel_city", lambda _thread_id: None)
    monkeypatch.setattr(process_replies, "send_reply", send_reply)
    monkeypatch.setattr(process_replies, "save_ai_reply", lambda *_args: None)
    monkeypatch.setattr(process_replies, "save_message", lambda *_args: None)
    monkeypatch.setattr(process_replies, "update_last_processed_message", lambda *_args: None)
    monkeypatch.setattr(process_replies, "update_conversation_status", lambda *_args: None)
    monkeypatch.setattr(process_replies, "mark_phone_requested", lambda *_args: None)
    monkeypatch.setattr(process_replies, "mark_phone_number_shared", lambda *_args: None)
    monkeypatch.setattr(process_replies, "release_conversation_claim", lambda *_args: None)


def test_assignment_is_deterministic_idempotent_and_logs_metadata(tmp_path):
    log_path = tmp_path / "assignments.jsonl"

    first = playbook_ab.assign("thread-001", PERSONA, str(log_path), now=10.0)
    second = playbook_ab.assign("thread-001", PERSONA, str(log_path), now=20.0)

    assert first == second
    assert log_path.read_text(encoding="utf-8").count("\n") == 1
    assert first["assigned_arm"] in {"A", "B"}
    assert first["propensity"] == 0.5
    assert first["assigned_at"] == 10.0
    assert {
        "assigned_arm",
        "assigned_design_id",
        "effective_design_id",
        "design_rules_applied",
        "expose_mobile",
        "landlord_number_requested",
        "landlord_phone_captured",
        "tenant_number_given_first",
        "conversation_progressed",
        "parked_or_dropped",
        "reply_received",
        "unsafe_or_pushy_detected",
    }.issubset(first)


def test_assignment_helper_is_noop_when_flag_off(monkeypatch, tmp_path):
    log_path = tmp_path / "assignments.jsonl"

    monkeypatch.delenv("PLAYBOOK_AB_ENABLED", raising=False)
    monkeypatch.setenv("PLAYBOOK_AB_LOG", str(log_path))

    assert process_replies._assign_playbook_ab_if_enabled("thread-001", PERSONA) is None
    assert not log_path.exists()


def test_assignment_helper_excludes_non_fresh_thread(monkeypatch, tmp_path):
    assignment_log = tmp_path / "assignments.jsonl"
    exclusion_log = tmp_path / "exclusions.jsonl"

    monkeypatch.setenv("PLAYBOOK_AB_ENABLED", "1")
    monkeypatch.setenv("PLAYBOOK_AB_LOG", str(assignment_log))
    monkeypatch.setenv("PLAYBOOK_AB_EXCLUSION_LOG", str(exclusion_log))
    monkeypatch.setattr(
        process_replies,
        "get_playbook_ab_enrollment_state",
        lambda _thread_id: {
            "outbound_count": 2,
            "inbound_count": 2,
            "message_contents": ["Initial enquiry", "Earlier AI reply"],
            "phone_found": False,
            "extracted_phone": None,
            "phone_found_at": None,
            "phone_requested_at": None,
            "last_ai_reply": "Earlier AI reply",
        },
    )

    assert process_replies._assign_playbook_ab_if_enabled(
        "thread-old",
        PERSONA,
    ) is None
    assert not assignment_log.exists()
    exclusion = json.loads(exclusion_log.read_text(encoding="utf-8").strip())
    assert exclusion["eligible"] is False
    assert "prior_automated_reply" in exclusion["reasons"]


def test_existing_assignment_remains_stable_when_thread_is_no_longer_fresh(
    monkeypatch,
    tmp_path,
):
    assignment_log = tmp_path / "assignments.jsonl"
    existing = playbook_ab.assign(
        "thread-existing",
        PERSONA,
        str(assignment_log),
        now=10.0,
        eligibility={"eligible": True, "reasons": []},
    )

    monkeypatch.setenv("PLAYBOOK_AB_ENABLED", "1")
    monkeypatch.setenv("PLAYBOOK_AB_LOG", str(assignment_log))
    monkeypatch.setattr(
        process_replies,
        "get_playbook_ab_enrollment_state",
        lambda _thread_id: (_ for _ in ()).throw(
            AssertionError("existing assignments must not be re-evaluated")
        ),
    )

    assert process_replies._assign_playbook_ab_if_enabled(
        "thread-existing",
        PERSONA,
    ) == existing


def test_enrollment_rejects_prior_capture_or_request():
    captured = playbook_ab.enrollment_eligibility(
        {
            "outbound_count": 1,
            "inbound_count": 1,
            "message_contents": ["Call me on 07123 456789"],
            "phone_found": False,
        }
    )
    requested = playbook_ab.enrollment_eligibility(
        {
            "outbound_count": 1,
            "inbound_count": 1,
            "message_contents": [],
            "phone_requested_at": datetime.utcnow(),
        }
    )

    assert captured["eligible"] is False
    assert "prior_phone_capture" in captured["reasons"]
    assert requested["eligible"] is False
    assert "prior_phone_request" in requested["reasons"]


def test_assignment_uses_stable_roughly_even_split():
    arms = [playbook_ab.arm_for_lead(f"thread-{i:04d}") for i in range(1000)]

    assert arms == [playbook_ab.arm_for_lead(f"thread-{i:04d}") for i in range(1000)]
    assert 0.45 <= arms.count("A") / len(arms) <= 0.55
    assert 0.45 <= arms.count("B") / len(arms) <= 0.55


def test_effective_config_preserves_control_and_routes_playbook():
    control = playbook_ab.effective_config("A")
    playbook = playbook_ab.effective_config("B")

    assert control["assigned_design_id"] is None
    assert control["effective_design_id"] == "viewing_first_v1"
    assert control["expose_mobile"] is True
    assert playbook["assigned_design_id"] == "playbook_ab_v1"
    assert playbook["effective_design_id"] == "playbook_ab_v1"
    assert playbook["expose_mobile"] is False


def test_playbook_prompt_is_dedicated_and_withholds_mobile():
    prompt = build_reply_prompt(
        'Tenant: "Hi, interested."\nLandlord: "What is your number?"',
        stage="VIEWING_DISCUSSION",
        persona=PERSONA,
        conversation_design_id="playbook_ab_v1",
        landlord_asked_for_number=True,
        outbound_count=0,
    )

    assert MOBILE not in prompt
    assert "Mobile number for this account: intentionally withheld" in prompt
    assert "Do not share the tenant mobile number" in prompt
    assert "park the lead politely" in prompt


def test_playbook_reply_path_does_not_use_phone_share_shortcut(monkeypatch):
    calls = []

    class DummyMessage:
        content = "Could I get your number just in case we're delayed getting there?"

    class DummyChoice:
        message = DummyMessage()

    class DummyResponse:
        choices = [DummyChoice()]

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return DummyResponse()

    monkeypatch.setattr("app.ai.replies._default_completion_create", fake_completion)

    reply, error = generate_reply(
        [{"sender": "landlord", "message": "Can you send me your WhatsApp number?"}],
        stage="VIEWING_DISCUSSION",
        persona=PERSONA,
        conversation_design_id="playbook_ab_v1",
        retries=1,
    )

    assert error is None
    assert calls
    assert MOBILE not in reply
    assert "get your number" in reply.lower()


def test_name_question_shortcut_assigns_before_sending(monkeypatch, tmp_path):
    log_path = tmp_path / "assignments.jsonl"
    sent_replies = []

    monkeypatch.setenv("PLAYBOOK_AB_ENABLED", "1")
    _patch_process_flow(monkeypatch, "What is your name?", log_path, sent_replies)

    import asyncio

    asyncio.run(process_replies.process_account_replies(DummyAccount(), object()))

    assert sent_replies == ["Of course, my name is Mary. Looking forward to meeting you."]
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["lead_id"] == "thread-shortcut"
    assert record["propensity"] == 0.5


def test_name_question_shortcut_flag_off_preserves_no_assignment(monkeypatch, tmp_path):
    log_path = tmp_path / "assignments.jsonl"
    sent_replies = []

    monkeypatch.delenv("PLAYBOOK_AB_ENABLED", raising=False)
    _patch_process_flow(
        monkeypatch,
        "What is your name?",
        log_path,
        sent_replies,
        expect_assignment=False,
    )

    import asyncio

    asyncio.run(process_replies.process_account_replies(DummyAccount(), object()))

    assert sent_replies == ["Of course, my name is Mary. Looking forward to meeting you."]
    assert not log_path.exists()


def test_normal_reply_path_assigns_before_generate_reply(monkeypatch, tmp_path):
    log_path = tmp_path / "assignments.jsonl"
    sent_replies = []

    monkeypatch.setenv("PLAYBOOK_AB_ENABLED", "1")
    _patch_process_flow(monkeypatch, "Could Saturday work?", log_path, sent_replies)

    def fake_generate_reply(*_args, **kwargs):
        assert log_path.exists()
        return "Saturday works for me.", None

    monkeypatch.setattr(process_replies, "generate_reply", fake_generate_reply)

    import asyncio

    asyncio.run(process_replies.process_account_replies(DummyAccount(), object()))

    assert sent_replies == ["Saturday works for me."]
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["lead_id"] == "thread-shortcut"
    assert record["assigned_design_id"] in {None, "playbook_ab_v1"}


def test_outcome_log_is_append_only_diagnostic_and_arm_free(tmp_path):
    outcome_log = tmp_path / "outcomes.jsonl"

    playbook_ab.log_outcome(
        "thread-001",
        str(outcome_log),
        reply_received=True,
        landlord_phone_captured=True,
        landlord_number_requested=True,
        tenant_number_given_first=False,
        conversation_progressed=True,
        parked_or_dropped=False,
        unsafe_or_pushy_detected=None,
    )
    playbook_ab.log_outcome("thread-001", str(outcome_log), reply_received=False)

    records = [
        json.loads(line)
        for line in outcome_log.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    assert {
        "reply_received",
        "landlord_phone_captured",
        "landlord_number_requested",
        "tenant_number_given_first",
        "conversation_progressed",
        "parked_or_dropped",
        "unsafe_or_pushy_detected",
    }.issubset(records[0])
    assert not {
        "arm",
        "assigned_arm",
        "assigned_design_id",
        "effective_design_id",
        "experiment",
    }.intersection(records[0])


def test_capture_is_logged_immediately_only_for_assigned_thread(monkeypatch, tmp_path):
    assignment_log = tmp_path / "assignments.jsonl"
    outcome_log = tmp_path / "outcomes.jsonl"
    playbook_ab.assign(
        "thread-001",
        PERSONA,
        str(assignment_log),
        eligibility={"eligible": True, "reasons": []},
    )
    monkeypatch.setenv("PLAYBOOK_AB_ENABLED", "1")
    monkeypatch.setenv("PLAYBOOK_AB_LOG", str(assignment_log))
    monkeypatch.setenv("PLAYBOOK_AB_OUTCOME_LOG", str(outcome_log))

    process_replies._log_playbook_ab_phone_capture("thread-unassigned")
    assert not outcome_log.exists()

    process_replies._log_playbook_ab_phone_capture("thread-001")
    record = json.loads(outcome_log.read_text(encoding="utf-8").strip())
    assert record["event"] == "phone_capture"
    assert record["landlord_phone_captured"] is True
    assert record["source_of_truth"] == "database.conversations.phone_found_at"


def test_database_capture_summary_counts_only_post_assignment_eligible_rows():
    assigned_at = datetime(2026, 6, 20, tzinfo=timezone.utc)
    assignments = [
        {
            "lead_id": "a-post",
            "assigned_arm": "A",
            "assigned_at": assigned_at.timestamp(),
            "eligibility": {"eligible": True, "reasons": []},
        },
        {
            "lead_id": "b-pre",
            "assigned_arm": "B",
            "assigned_at": assigned_at.timestamp(),
            "eligibility": {"eligible": True, "reasons": []},
        },
        {
            "lead_id": "legacy",
            "assigned_arm": "B",
            "assigned_at": assigned_at.timestamp(),
        },
    ]
    outcomes = {
        "a-post": {
            "phone_found": True,
            "phone_found_at": assigned_at + timedelta(hours=1),
        },
        "b-pre": {
            "phone_found": True,
            "phone_found_at": assigned_at - timedelta(hours=1),
        },
        "legacy": {
            "phone_found": True,
            "phone_found_at": assigned_at + timedelta(hours=1),
        },
    }

    report = playbook_ab.summarize_database_captures(assignments, outcomes)

    assert report["source_of_truth"] == "database.conversations.phone_found_at"
    assert report["arms"]["A"] == {
        "assigned": 1,
        "captured": 1,
        "capture_rate": 1.0,
    }
    assert report["arms"]["B"] == {
        "assigned": 1,
        "captured": 0,
        "capture_rate": 0.0,
    }
    assert report["excluded"] == [
        {"lead_id": "legacy", "reason": "legacy_missing_eligibility"}
    ]

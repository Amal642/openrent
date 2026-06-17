import json

from app.ai.prompts import build_reply_prompt
from app.ai.replies import generate_reply
from app.experiments import playbook_ab


MOBILE = "+447743722832"
PERSONA = {
    "persona_name": "Mary",
    "mobile_number": MOBILE,
    "phone_fetching_type": "immediate",
    "conversation_style": "warm_casual",
    "persona_type": "young_professional_couple",
    "persona_partner_name": "Alex",
}


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

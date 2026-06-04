"""
Cross-function calibration seeds for ARM_A.

Each mutation is in a HELPER function (function B), but the failing test
calls a HIGH-LEVEL function (function A) that depends on B.

When ARM_A runs, the extractor surfaces function A's source (correct).
The proposer cannot locate the bug because it only sees A.
The verifier patches B — but the model always proposes a fix for A.
This models the cross-function regime where retrieval adds value.

Target ARM_A first-attempt pass rate: <20%.
The 100% rate on isolated seeds drops here because local context is insufficient.
"""

SEEDS_CROSS = [
    {
        "case_id": "cross_001",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_stage_booking_confirmed_after_long_discussion",
        "target_file": "app/ai/stages.py",
        "target_function": "_recent_messages",
        "failure_mode": "cross_function_wrong_slice_direction",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore [-limit:] in _recent_messages; [:limit] returns the FIRST N messages "
            "instead of the LAST N. With 11 messages, the booking confirmation (messages 9-11) "
            "is outside the first 8, so detect_stage only sees discussion and returns VIEWING_DISCUSSION. "
            "ARM_A sees detect_stage source (correct) and cannot locate the slicing bug."
        ),
        "original_snippet": "    return list(messages or [])[-limit:]",
        "mutated_snippet":  "    return list(messages or [])[:limit]",
    },
    {
        "case_id": "cross_002",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_landlord_attitude_inbound_aggression_detected",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "landlord_messages",
        "failure_mode": "cross_function_sender_set_trimmed",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore {'landlord', 'inbound'} in landlord_messages; dropping 'inbound' means "
            "OpenRent-labelled messages from landlords are excluded. detect_landlord_attitude "
            "receives an empty list and returns 'responsive' instead of 'aggressive'. "
            "ARM_A sees detect_landlord_attitude source (correct) and cannot find the sender-set bug."
        ),
        "original_snippet": '        if _sender(message) in {"landlord", "inbound"}',
        "mutated_snippet":  '        if _sender(message) in {"landlord"}',
    },
    {
        "case_id": "cross_003",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_latest_landlord_asked_for_phone_detects_phone_keyword",
        "target_file": "app/ai/personas.py",
        "target_function": "landlord_asked_for_phone",
        "failure_mode": "cross_function_keyword_pattern_truncated",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore 'phone|' at the start of the first regex in landlord_asked_for_phone (personas.py). "
            "The test message uses 'phone' as the ONLY contact keyword — no 'mobile', 'number', etc. "
            "Without 'phone' in the pattern, the first regex fails → function returns False. "
            "ARM_A sees latest_landlord_asked_for_phone (a 3-line wrapper) and cannot see "
            "landlord_asked_for_phone's pattern in personas.py."
        ),
        "original_snippet": '            r"\\b(phone|mobile|number|contact|whatsapp|whats\\s*app|call|text)\\b",',
        "mutated_snippet":  '            r"\\b(mobile|number|contact|whatsapp|whats\\s*app|call|text)\\b",',
    },
    {
        "case_id": "cross_004",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_viewing_requested_finds_keyword_in_message_key",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "_content",
        "failure_mode": "cross_function_wrong_message_key",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore 'message' as the primary key in _content; using 'body' means messages stored "
            "under the 'message' key return empty string. viewing_requested then scans blank text "
            "and returns False. ARM_A sees viewing_requested source (correct) — it builds a join "
            "of _content() calls that look fine."
        ),
        "original_snippet": '    return str(message.get("message") or message.get("content") or "")',
        "mutated_snippet":  '    return str(message.get("body") or message.get("content") or "")',
    },
    {
        "case_id": "cross_005",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_stage_single_booked_pattern_is_sufficient",
        "target_file": "app/ai/stages.py",
        "target_function": "_matches_any",
        "failure_mode": "cross_function_any_vs_all",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore any() in _matches_any; all() requires EVERY pattern in the list to match, "
            "which is impossible for BOOKED_PATTERNS (10 items). detect_stage's booking checks "
            "always return False, so VIEWING_BOOKED is never returned. "
            "ARM_A sees detect_stage source (correct calls to _matches_any) and proposes wrong "
            "changes to detect_stage instead of fixing the helper."
        ),
        "original_snippet": "    return any(re.search(pattern, text, re.I) for pattern in patterns)",
        "mutated_snippet":  "    return all(re.search(pattern, text, re.I) for pattern in patterns)",
    },
    {
        "case_id": "cross_006",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_outbound_count_reads_sender_key",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "_sender",
        "failure_mode": "cross_function_wrong_sender_key",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore 'sender' as the primary key in _sender; using 'from' means all messages "
            "with only a 'sender' key are treated as senderless. outbound_count then matches "
            "nothing and returns 0. ARM_A sees outbound_count source (the set-membership check "
            "looks correct) and cannot find that _sender is returning empty strings."
        ),
        "original_snippet": '    return str(message.get("sender") or message.get("direction") or "").lower()',
        "mutated_snippet":  '    return str(message.get("from") or message.get("direction") or "").lower()',
    },
    {
        "case_id": "cross_007",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_phone_shared_state_detects_tenant_sender",
        "target_file": "app/ai/personas.py",
        "target_function": "tenant_shared_phone",
        "failure_mode": "cross_function_sender_scan_excludes_tenant",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore 'tenant' in the sender set inside tenant_shared_phone (personas.py); "
            "without it, messages from the 'tenant' sender are skipped entirely and the phone "
            "number is never found. phone_shared_state returns False. ARM_A sees phone_shared_state "
            "source (a 3-line wrapper that just calls tenant_shared_phone) — it has no visibility "
            "into the sender set in personas.py."
        ),
        "original_snippet": '        if sender not in {"user", "tenant", "outbound", "ai"}:',
        "mutated_snippet":  '        if sender not in {"user", "outbound", "ai"}:',
    },
]

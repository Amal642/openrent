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

    # ── OPEN-53 expansion ──────────────────────────────────────────────────────
    # cross_008–cross_013 : name-hidden (B absent from test docstring)
    # cross_014–cross_020 : name-visible (B named in test docstring)
    # cross_015           : depth-2 (B not directly called by A)

    {
        "case_id": "cross_008",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_stage_booking_in_message_field",
        "target_file": "app/ai/stages.py",
        "target_function": "_message_text",
        "failure_mode": "cross_function_wrong_message_key",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore 'message' as the primary key in _message_text (stages.py). "
            "Using 'body' means all message text is read as empty string. "
            "detect_stage then finds no booking patterns and returns None instead of VIEWING_BOOKED. "
            "ARM_A sees detect_stage source, which calls _message_text — fix is invisible."
        ),
        "original_snippet": '    return str(message.get("message") or message.get("content") or "")',
        "mutated_snippet":  '    return str(message.get("body") or message.get("content") or "")',
    },
    {
        "case_id": "cross_009",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_stage_booking_requires_time_confirmation",
        "target_file": "app/ai/stages.py",
        "target_function": "_has_time",
        "failure_mode": "cross_function_has_time_always_false",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore the time-presence check in _has_time. Returning False unconditionally means "
            "detect_stage cannot confirm a booking via the 'booked pattern + time present' path. "
            "The combined booking context has patterns but _has_time returns False, so the check "
            "fails and detect_stage falls through to None. "
            "ARM_A sees detect_stage source and cannot locate _has_time."
        ),
        "original_snippet": "        not _overlaps_any(match.span(), date_spans)",
        "mutated_snippet":  "        False",
    },
    {
        "case_id": "cross_010",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_extract_viewing_datetime_tomorrow_resolves_to_next_day",
        "target_file": "app/ai/stages.py",
        "target_function": "_target_date_from_text",
        "failure_mode": "cross_function_tomorrow_keyword_removed",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore 'tomorrow' as a keyword in _target_date_from_text. "
            "Changing it to 'yesterday' means 'tomorrow at 3pm' is not recognized as tomorrow's date; "
            "the function falls through to today's date, returning the wrong datetime. "
            "ARM_A sees extract_viewing_datetime and cannot find the keyword bug in the helper."
        ),
        "original_snippet": '    if "tomorrow" in text:',
        "mutated_snippet":  '    if "yesterday" in text:',
    },
    {
        "case_id": "cross_011",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_extract_viewing_datetime_time_without_date",
        "target_file": "app/ai/stages.py",
        "target_function": "_date_spans",
        "failure_mode": "cross_function_date_spans_fake_huge_span",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore _date_spans to return actual date match spans. "
            "Returning a fake huge span [(0, 10000)] causes every time match to 'overlap' with a date, "
            "so _overlaps_any filters all candidates out and extract_viewing_datetime returns None "
            "even for clean time-only messages. ARM_A sees extract_viewing_datetime and cannot "
            "find the date-span corruption in the helper."
        ),
        "original_snippet": "    return [match.span() for match in NUMERIC_DATE_PATTERN.finditer(text)]",
        "mutated_snippet":  "    return [(0, 10000)]",
    },
    {
        "case_id": "cross_012",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_get_conversation_style_resolves_alias",
        "target_file": "app/ai/personas.py",
        "target_function": "normalize_conversation_style",
        "failure_mode": "cross_function_alias_resolution_broken",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore STYLE_ALIASES lookup in normalize_conversation_style. "
            "Returning the raw style string for unrecognized names means aliases like "
            "'friendly_couple' pass through unresolved. get_conversation_style then tries "
            "CONVERSATION_STYLES['friendly_couple'] and raises KeyError. "
            "ARM_A sees get_conversation_style which calls normalize_conversation_style — fix "
            "is in the helper."
        ),
        "original_snippet": '    return STYLE_ALIASES.get(style, "friendly_viewing")',
        "mutated_snippet":  '    return style',
    },
    {
        "case_id": "cross_013",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_should_share_phone_respects_immediate_style_alias",
        "target_file": "app/ai/personas.py",
        "target_function": "normalize_conversation_style",
        "failure_mode": "cross_function_alias_resolution_broken",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore STYLE_ALIASES lookup in normalize_conversation_style. "
            "With alias resolution broken, 'direct_professional' is not resolved to "
            "'direct_number_request', so should_share_phone_now treats the style as unknown "
            "and falls back to the conservative phone_fetching_type='delayed' path, returning False "
            "instead of True. ARM_A sees should_share_phone_now and cannot locate the alias bug."
        ),
        "original_snippet": '    return STYLE_ALIASES.get(style, "friendly_viewing")',
        "mutated_snippet":  '    return style',
    },
    {
        "case_id": "cross_014",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_landlord_attitude_aggressive_from_message_field",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "_content",
        "failure_mode": "cross_function_wrong_message_key",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore 'message' as the primary key in _content (conversation_memory.py). "
            "Using 'body' means _content returns empty string for messages stored under 'message'. "
            "detect_landlord_attitude's pattern matching is applied to empty text and defaults to "
            "'responsive'. ARM_A sees detect_landlord_attitude, which calls _content — fix invisible."
        ),
        "original_snippet": '    return str(message.get("message") or message.get("content") or "")',
        "mutated_snippet":  '    return str(message.get("body") or message.get("content") or "")',
    },
    {
        "case_id": "cross_015",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_landlord_attitude_sender_case_sensitivity",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "_sender",
        "failure_mode": "cross_function_sender_uppercase",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore .lower() in _sender. Returning uppercase sender values means landlord_messages "
            "checks 'LANDLORD' in {'landlord', 'inbound'} → False, so no landlord messages are "
            "returned. detect_landlord_attitude sees an empty landlord list and defaults to "
            "'responsive'. ARM_A sees detect_landlord_attitude, which calls landlord_messages; "
            "_sender is an indirect (depth-2) dependency not shown to ARM_A."
        ),
        "original_snippet": '    return str(message.get("sender") or message.get("direction") or "").lower()',
        "mutated_snippet":  '    return str(message.get("sender") or message.get("direction") or "").upper()',
    },
    {
        "case_id": "cross_016",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_phone_shared_state_digit_extraction",
        "target_file": "app/ai/personas.py",
        "target_function": "tenant_shared_phone",
        "failure_mode": "cross_function_digit_strip_inverted",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore r'\\D' (non-digit strip) in tenant_shared_phone. Using r'\\d' strips digits "
            "instead of non-digits, so content_digits contains only letters and punctuation. "
            "The phone number can never be found in a digit-free string and phone_shared_state "
            "always returns False. ARM_A sees phone_shared_state — fix is in tenant_shared_phone."
        ),
        "original_snippet": '        content_digits = re.sub(r"\\D", "", str(message.get("message") or message.get("content") or ""))',
        "mutated_snippet":  '        content_digits = re.sub(r"\\d", "", str(message.get("message") or message.get("content") or ""))',
    },
    {
        "case_id": "cross_017",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_outbound_count_case_insensitive_sender",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "_sender",
        "failure_mode": "cross_function_sender_uppercase",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore .lower() in _sender. Returning uppercase values ('TENANT', 'OUTBOUND') means "
            "outbound_count's set membership check in lowercase {'user', 'tenant', 'outbound', 'ai'} "
            "always fails and returns 0. ARM_A sees outbound_count source which calls _sender — "
            "the bug is in the helper."
        ),
        "original_snippet": '    return str(message.get("sender") or message.get("direction") or "").lower()',
        "mutated_snippet":  '    return str(message.get("sender") or message.get("direction") or "").upper()',
    },
    {
        "case_id": "cross_018",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_extract_viewing_datetime_time_not_excluded_when_no_dates",
        "target_file": "app/ai/stages.py",
        "target_function": "_overlaps_any",
        "failure_mode": "cross_function_overlaps_any_always_true",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore the actual overlap check in _overlaps_any. Returning True unconditionally means "
            "every time match 'overlaps' with date spans (even an empty list), so all time candidates "
            "are filtered out in extract_viewing_datetime and it returns None. "
            "ARM_A sees extract_viewing_datetime — _overlaps_any is the hidden dependency."
        ),
        "original_snippet": "    return any(start < other_end and end > other_start for other_start, other_end in spans)",
        "mutated_snippet":  "    return True",
    },
    {
        "case_id": "cross_019",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_detect_stage_reschedule_mid_sentence",
        "target_file": "app/ai/stages.py",
        "target_function": "_matches_any",
        "failure_mode": "cross_function_search_vs_match",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore re.search in _matches_any. Using re.match checks only at the start of the "
            "string, so patterns like r'\\breschedule\\b' fail to match mid-sentence text like "
            "'I need to reschedule our appointment.' detect_stage returns None instead of "
            "VIEWING_DISCUSSION. ARM_A sees detect_stage which calls _matches_any — fix in helper."
        ),
        "original_snippet": "    return any(re.search(pattern, text, re.I) for pattern in patterns)",
        "mutated_snippet":  "    return any(re.match(pattern, text, re.I) for pattern in patterns)",
    },
    {
        "case_id": "cross_020",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_cross_function.py::test_landlord_messages_reads_direction_key",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "_sender",
        "failure_mode": "cross_function_direction_key_dropped",
        "triage_ground_truth": "cross_function",
        "expected_fix_summary": (
            "Restore the 'direction' fallback in _sender. Without it, messages that use 'direction' "
            "instead of 'sender' (OpenRent's outbound format) return empty string from _sender. "
            "landlord_messages then sees '' which is not in {'landlord', 'inbound'} and filters "
            "them out. ARM_A sees landlord_messages source — the bug is in _sender."
        ),
        "original_snippet": '    return str(message.get("sender") or message.get("direction") or "").lower()',
        "mutated_snippet":  '    return str(message.get("sender") or "").lower()',
    },
]

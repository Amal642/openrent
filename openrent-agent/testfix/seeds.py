"""
Seeded mutation definitions for ARM_A baseline.

Each entry describes one plausible single-line bug introduced into a real
OpenRent function. The seeder applies the mutation, confirms the targeted test
FAILS, then records the result in baseline_cases.jsonl.

original_snippet / mutated_snippet use exact text replacement (str.replace, count=1).
Snippets are chosen to be unique within their function body.
"""

SEEDS = [
    {
        "case_id": "seed_001",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_regex_extract_phone_uk_mobile_11_digits",
        "target_file": "app/ai/extractors.py",
        "target_function": "regex_extract_phone",
        "failure_mode": "regex_pattern_missing_case",
        "expected_fix_summary": "Restore 07\\d{9} (11-digit UK mobile); \\d{10} requires 12 digits and misses all standard mobiles.",
        # Mutation: pattern requires one extra digit — never matches a real 11-digit UK mobile
        "original_snippet": r'r"(07\d{9})"',
        "mutated_snippet":  r'r"(07\d{10})"',
    },
    {
        "case_id": "seed_002",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_detect_landlord_attitude_aggressive_beats_polite_opener",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "detect_landlord_attitude",
        "failure_mode": "wrong_conditional",
        "expected_fix_summary": "Restore return 'aggressive' in the aggressive-pattern branch; 'suspicious' is the wrong label.",
        # Mutation: aggressive branch returns the wrong attitude label
        "original_snippet": '        return "aggressive"',
        "mutated_snippet":  '        return "suspicious"',
    },
    {
        "case_id": "seed_003",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_extract_viewing_datetime_same_weekday_means_next_week",
        "target_file": "app/ai/stages.py",
        "target_function": "extract_viewing_datetime",
        "failure_mode": "off_by_one_date_window",
        "expected_fix_summary": "Restore days_ahead = 7; using 6 maps 'next Monday' to Sunday (wrong day).",
        # Mutation: same-weekday fallback advances 6 days instead of 7
        "original_snippet": "                days_ahead = 7",
        "mutated_snippet":  "                days_ahead = 6",
    },
    {
        "case_id": "seed_004",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_outbound_count_handles_none_messages",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "outbound_count",
        "failure_mode": "missing_none_handling",
        "expected_fix_summary": "Restore 'messages or []' guard; iterating over None raises TypeError.",
        # Mutation: drop the None guard so None raises TypeError
        "original_snippet": "        for message in messages or []",
        "mutated_snippet":  "        for message in messages",
    },
    {
        "case_id": "seed_005",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_is_valid_reply_empty_string_is_invalid",
        "target_file": "app/ai/validators.py",
        "target_function": "is_valid_reply",
        "failure_mode": "wrong_status_transition",
        "expected_fix_summary": "Restore return False in the null guard; returning True passes empty/None as valid replies into the send path.",
        # Mutation: null guard returns True instead of False — empty replies accepted as valid
        "original_snippet": "    if not reply:\n        return False\n\n    reply = reply.strip()",
        "mutated_snippet":  "    if not reply:\n        return True\n\n    reply = reply.strip()",
    },
    {
        "case_id": "seed_006",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_landlord_messages_excludes_tenant_messages",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "landlord_messages",
        "failure_mode": "duplicate_counting_issue",
        "expected_fix_summary": "Remove 'tenant' from the landlord sender set; including it double-counts tenant messages as landlord messages.",
        # Mutation: tenant sender added to the landlord set — counts tenant messages as landlord
        "original_snippet": '        if _sender(message) in {"landlord", "inbound"}',
        "mutated_snippet":  '        if _sender(message) in {"landlord", "inbound", "tenant"}',
    },
    {
        "case_id": "seed_007",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_normalize_uk_phone_plus44_prefix_converts_correctly",
        "target_file": "app/utils/phone.py",
        "target_function": "normalize_uk_phone",
        "failure_mode": "parser_edge_case",
        "expected_fix_summary": "Restore phone[3:]; phone[4:] skips the first digit after +44, producing a 10-digit number instead of 11.",
        # Mutation: slice off one extra digit when stripping the +44 prefix
        "original_snippet": '            "0" + phone[3:]',
        "mutated_snippet":  '            "0" + phone[4:]',
    },
    {
        "case_id": "seed_008",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_fallback_distant_location_varies_by_input",
        "target_file": "app/ai/replies.py",
        "target_function": "_fallback_distant_location",
        "failure_mode": "return_value_mismatch",
        "expected_fix_summary": "Restore 'if not property_location'; inverting the guard returns Manchester for every real location and None for missing input.",
        # Mutation: guard condition inverted — returns 'Manchester' for any real location
        "original_snippet": "    if not property_location:",
        "mutated_snippet":  "    if property_location:",
    },
    {
        "case_id": "seed_009",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_remove_unapproved_phone_numbers_none_input_returns_none",
        "target_file": "app/ai/validators.py",
        "target_function": "remove_unapproved_phone_numbers",
        "failure_mode": "exception_path",
        "expected_fix_summary": "Restore the 'if not reply: return reply' guard; without it, None is passed to re.sub and raises TypeError.",
        # Mutation: remove the None short-circuit so None reaches re.sub and raises
        "original_snippet": "    if not reply:\n        return reply\n\n    allowed_exact",
        "mutated_snippet":  "    allowed_exact",
    },
    {
        "case_id": "seed_010",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_baseline.py::test_normalize_place_name_truncates_four_words_to_three",
        "target_file": "app/ai/replies.py",
        "target_function": "_normalize_place_name",
        "failure_mode": "boundary_value",
        "expected_fix_summary": "Restore words[:3]; words[:2] truncates a valid 3-word name to 2 words when input has 4+ words.",
        # Mutation: truncate to 2 words instead of 3
        "original_snippet": "        words = words[:3]",
        "mutated_snippet":  "        words = words[:2]",
    },
]

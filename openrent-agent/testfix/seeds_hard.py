"""
Hard calibration seeds for ARM_A.

Design criteria for each mutation:
  - Error signal is ambiguous: the test failure does not reveal the exact edit needed.
  - Multiple plausible wrong fixes exist in the function body.
  - At least one case requires codebase-convention knowledge not visible in one function.

Target ARM_A first-attempt pass rate: 40-70%.
If actual rate >75% these seeds are still too easy.
If actual rate <20% the context given to the proposer is too starved.
"""

SEEDS_HARD = [
    {
        "case_id": "hard_001",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_hard.py::test_extract_viewing_datetime_uses_last_confirmed_time_not_first",
        "target_file": "app/ai/stages.py",
        "target_function": "extract_viewing_datetime",
        "failure_mode": "wrong_candidate_selection_order",
        "expected_fix_summary": (
            "Restore candidates[-1]; candidates[0] picks the FIRST time mention "
            "(the 2pm option) instead of the LAST confirmed time (5pm)."
        ),
        # Mutation: take first candidate instead of last — wrong time extracted when
        # multiple times appear. Error shows wrong hour, not wrong index.
        "original_snippet": "    combined, time_match = candidates[-1]",
        "mutated_snippet":  "    combined, time_match = candidates[0]",
    },
    {
        "case_id": "hard_002",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_hard.py::test_detect_stage_confirmed_booking_with_time_returns_viewing_booked",
        "target_file": "app/ai/stages.py",
        "target_function": "detect_stage",
        "failure_mode": "status_stage_logic_ambiguity",
        "expected_fix_summary": (
            "Restore return VIEWING_BOOKED inside the combined_booking block; "
            "the mutation makes it return VIEWING_DISCUSSION there, but 4 other "
            "VIEWING_DISCUSSION returns in the function make the wrong one hard to identify."
        ),
        # Mutation: the first return VIEWING_BOOKED (inside combined_booking check)
        # becomes VIEWING_DISCUSSION. Error: 'VIEWING_DISCUSSION' when VIEWING_BOOKED
        # expected. But the function has 4 legitimate VIEWING_DISCUSSION returns —
        # the model must trace the booking_context path to find the wrong one.
        "original_snippet": (
            "            return VIEWING_BOOKED\n"
            "        if _matches_any(latest_text, BOOKED_PATTERNS):"
        ),
        "mutated_snippet": (
            "            return VIEWING_DISCUSSION\n"
            "        if _matches_any(latest_text, BOOKED_PATTERNS):"
        ),
    },
    {
        "case_id": "hard_003",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_hard.py::test_normalize_uk_phone_bare_44_prefix_no_plus",
        "target_file": "app/utils/phone.py",
        "target_function": "normalize_uk_phone",
        "failure_mode": "phone_normalization_convention",
        "expected_fix_summary": (
            "Restore startswith('44'); '440' is a non-existent prefix so the elif "
            "branch never fires, leaving bare 44-numbers un-normalized. "
            "The fix requires knowing that UK country code is '44', not '440'."
        ),
        # Mutation: 44-prefix check becomes 440 — a plausible-looking typo.
        # Error: '447911123456' instead of '07911123456'. Plausible wrong fixes:
        # change to '447', change the slice, handle it with a regex instead.
        "original_snippet": '    elif phone.startswith("44"):',
        "mutated_snippet":  '    elif phone.startswith("440"):',
    },
    {
        "case_id": "hard_004",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_hard.py::test_detect_landlord_attitude_slow_reply_on_long_gap",
        "target_file": "app/ai/conversation_memory.py",
        "target_function": "detect_landlord_attitude",
        "failure_mode": "boundary_datetime_behaviour",
        "expected_fix_summary": (
            "Restore latest_time - previous_time; reversing the subtraction produces "
            "a negative timedelta that is never > 24h, so slow_reply is never returned. "
            "The model must identify the subtraction order, not just the threshold value."
        ),
        # Mutation: subtraction reversed. For chronological messages,
        # previous_time - latest_time is negative, so condition is always False.
        # Error: 'responsive' instead of 'slow_reply'. Plausible wrong fixes:
        # reduce the threshold, change >= to >, change the return value.
        "original_snippet": "        if latest_time - previous_time > timedelta(hours=24):",
        "mutated_snippet":  "        if previous_time - latest_time > timedelta(hours=24):",
    },
    {
        "case_id": "hard_005",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_hard.py::test_regex_extract_phone_preserves_plus_prefix",
        "target_file": "app/ai/extractors.py",
        "target_function": "regex_extract_phone",
        "failure_mode": "edge_case_parser_behaviour",
        "expected_fix_summary": (
            "Restore r'[^\\d+]' in the cleaned sub; removing '+' from the allowed set "
            "strips the + before pattern matching, so \\+44\\d{10,12} never matches and "
            "the 447... fallback pattern fires instead, losing the + prefix. "
            "Plausible wrong fixes: add + to the return, change the first pattern, "
            "add a post-processing step."
        ),
        # Mutation: + stripped from the character class used to clean input.
        # '+447911123456' becomes '447911123456' before pattern matching.
        # The \+44 pattern misses; the 447 fallback matches without the +.
        # Error: '447911123456' instead of '+447911123456'.
        "original_snippet": '    cleaned = re.sub(r"[^\\d+]", "", combined)',
        "mutated_snippet":  '    cleaned = re.sub(r"[^\\d]", "", combined)',
    },
    {
        "case_id": "hard_006",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_hard.py::test_extract_viewing_datetime_without_now_does_not_raise",
        "target_file": "app/ai/stages.py",
        "target_function": "extract_viewing_datetime",
        "failure_mode": "none_failure_fallback_behaviour",
        "expected_fix_summary": (
            "Restore 'now = now or datetime.utcnow()'; without the fallback, "
            "now stays None and 'candidate < now' raises TypeError. "
            "Plausible wrong fixes: guard the comparison, return None early, "
            "use a different default."
        ),
        # Mutation: remove the datetime.utcnow() fallback from the now guard.
        # now=None reaches 'if candidate < now' and raises TypeError.
        # Error is a TypeError, not an AssertionError — tests the exception path.
        "original_snippet": "    now = now or datetime.utcnow()",
        "mutated_snippet":  "    now = now",
    },
    {
        "case_id": "hard_007",
        "source_type": "seeded_realistic",
        "test_id": "tests/test_arm_a_hard.py::test_detect_stage_uses_most_recent_message_not_oldest",
        "target_file": "app/ai/stages.py",
        "target_function": "detect_stage",
        "failure_mode": "cross_function_convention",
        "expected_fix_summary": (
            "Restore recent[-1]; recent[0] picks the oldest message as 'latest', "
            "so an early reschedule request triggers VIEWING_DISCUSSION even after "
            "a subsequent confirmed booking. The fix requires knowing the codebase "
            "convention that lists are ordered oldest-first (newest at -1)."
        ),
        # Mutation: latest_text assigned from the FIRST (oldest) message.
        # An early reschedule in recent[0] fires the explicit reschedule check,
        # returning VIEWING_DISCUSSION instead of VIEWING_BOOKED.
        # Error: 'VIEWING_DISCUSSION' when VIEWING_BOOKED expected — same error as
        # hard_002 but from a completely different location in the function.
        "original_snippet": "    latest_text = _message_text(recent[-1]).lower()",
        "mutated_snippet":  "    latest_text = _message_text(recent[0]).lower()",
    },
]

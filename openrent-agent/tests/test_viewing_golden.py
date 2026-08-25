"""Golden-thread regression fixtures.

These are REAL problem threads from production, frozen (messages + timestamps)
so the exact time-resolution bugs we fixed cannot silently come back. Each
fixture asserts the resolver / stale-date guard produces the correct result.

If you change viewing-time handling and one of these fails, you have
reintroduced a real, observed no-show / wrong-date bug. Do not "fix" the test
by editing the expected value — fix the code.
"""
from datetime import datetime

from app.ai.stages import resolve_viewing_datetime, correct_stale_viewing_day
from app.utils.scheduling import uk_naive_to_utc_naive as U


# --- Thread 45969788 (Highbury New Park) ------------------------------------
# Bug: off-by-one-day. Agreed 1pm on the viewing day (Fri 21 Aug); the LLM
# resolved "tomorrow"/stale echoes to 22 Aug, disabling the no-show safeguards.
# Also: en-route "running late" + the stale "1pm tomorrow" reply on the day.
THREAD_45969788 = [
    {"sender": "us", "message": "Hi, I'm interested in the 2 bed property... structural engineer and commercial manager, so stable jobs. Could you let me know when a viewing might be possible?", "timestamp": "2026-08-19T21:09:15"},
    {"sender": "landlord", "message": "Hello, have you seen the virtual tour video? If so, then I can arrange a viewing for the coming day.", "timestamp": "2026-08-19T21:44:17"},
    {"sender": "us", "message": "I've had a look at the virtual tour, thanks. would tomorrow afternoon work for you?", "timestamp": "2026-08-19T21:44:26"},
    {"sender": "landlord", "message": "Hi, the flat is currently tenanted so id need to check with the tenants. However I'd be in the area around 1pm if that works?", "timestamp": "2026-08-20T07:23:58"},
    {"sender": "us", "message": "1pm tomorrow sounds fine, I'm happy to come then if the tenants are okay with it.", "timestamp": "2026-08-20T07:24:07"},
    {"sender": "landlord", "message": "Hi Charlotte,\nIts now Thursday so I meant 1pm today. If that can work please let me know and ill ask the tenants", "timestamp": "2026-08-20T08:07:01"},
    {"sender": "us", "message": "Sorry, I can't make it today on short notice. If the tenants are free another day, I'm happy to come then.", "timestamp": "2026-08-20T08:07:10"},
    {"sender": "landlord", "message": "Sure ok, then 1pm tomorrow will be fine", "timestamp": "2026-08-20T08:51:20"},
    {"sender": "us", "message": "That works for me, thanks. Please let me know if the tenants are happy with that time.", "timestamp": "2026-08-20T08:51:28"},
    {"sender": "landlord", "message": "Yes they are. I dont believe they will be in", "timestamp": "2026-08-20T10:21:58"},
    {"sender": "us", "message": "Perfect, thanks for confirming. I'll see you at 1pm tomorrow then. Could you send me your number so I can get in touch if needed?", "timestamp": "2026-08-20T10:22:08"},
    {"sender": "landlord", "message": "I'm not sure if its me or Joanna doing the viewing so the best thing would be to message through openrent", "timestamp": "2026-08-20T10:58:44"},
    {"sender": "us", "message": "That's fine, I'll keep an eye on messages here then. Looking forward to tomorrow at 1pm.", "timestamp": "2026-08-20T10:58:52"},
    {"sender": "landlord", "message": "Hi Charlotte, the address is 159 Highbury New Park. See you", "timestamp": "2026-08-21T07:35:54"},
    {"sender": "us", "message": "Thanks, I'll be there at 1pm tomorrow. Looking forward to seeing the place.", "timestamp": "2026-08-21T07:36:02"},
    {"sender": "landlord", "message": "Hi Charlotte,\nRunning 5-10min", "timestamp": "2026-08-21T11:58:07"},
    {"sender": "landlord", "message": "More like 5 min late", "timestamp": "2026-08-21T11:58:07"},
    {"sender": "us", "message": "No worries, I'll be there at 1pm. See you soon.", "timestamp": "2026-08-21T11:58:13"},
]


def test_golden_45969788_deterministic_only_gets_correct_day():
    # No LLM: the message-anchored resolver alone must land on 21 Aug, not 22.
    resolved = resolve_viewing_datetime(THREAD_45969788, now=datetime(2026, 8, 21, 12, 0))
    assert resolved == datetime(2026, 8, 21, 13, 0)  # UK-local
    assert U(resolved) == datetime(2026, 8, 21, 12, 0)  # stored UTC (BST -1h)


def test_golden_45969788_overrides_wrong_llm_date():
    # The LLM produced 22 Aug (the actual bug); resolver must override to 21 Aug.
    llm = {"viewing_arranged": True, "viewing_datetime": "2026-08-22 13:00"}
    resolved = resolve_viewing_datetime(THREAD_45969788, llm_detection=llm, now=datetime(2026, 8, 21, 12, 0))
    assert resolved == datetime(2026, 8, 21, 13, 0)


def test_golden_45969788_stale_reply_corrected():
    # The stale outbound reply on the viewing day must be corrected today.
    viewing_utc = datetime(2026, 8, 21, 12, 0)  # 13:00 UK
    reply = "Thanks, I'll be there at 1pm tomorrow. Looking forward to seeing the place."
    fixed = correct_stale_viewing_day(reply, viewing_utc, now=datetime(2026, 8, 21, 6, 36))
    assert fixed == "Thanks, I'll be there at 1pm today. Looking forward to seeing the place."


# --- Thread 45987890 (Tudor Street) -----------------------------------------
# Bug class: a single message names TWO times ("make it 4:30 ... booked for
# 4pm"). The regex grabs the last (4pm, the OTHER viewing); the LLM understands
# the agreed slot is 4:30. Resolver must land on 16:30, not 16:00.
THREAD_45987890 = [
    {"sender": "us", "message": "Hi, I'm interested in the 1 bed property... mechanical engineer and civil engineer. Could you let me know when it would be possible to arrange a viewing?", "timestamp": "2026-08-20T15:26:25"},
    {"sender": "landlord", "message": "Hi Sophie, I'd be happy to arrange a viewing. I have availability this Friday afternoon or anytime over the weekend, whichever suits you best.", "timestamp": "2026-08-20T16:04:25"},
    {"sender": "us", "message": "Friday afternoon works well for us. What time did you have in mind?", "timestamp": "2026-08-20T16:04:33"},
    {"sender": "landlord", "message": "4-5 pm work well for me", "timestamp": "2026-08-20T16:52:36"},
    {"sender": "us", "message": "4 pm on Friday sounds perfect, thanks. Could I have your number to confirm on the day?", "timestamp": "2026-08-20T16:52:46"},
    {"sender": "landlord", "message": "Hi Sophie, can we make it 4:30 as I already have another viewing booked for 4pm? My number is +44 7985 519520", "timestamp": "2026-08-20T17:57:22"},
]


def test_golden_45987890_reschedule_takes_agreed_time_not_other_viewing():
    # The LLM (correctly) reads the agreed slot as 4:30; the regex would take the
    # trailing "4pm" (the landlord's OTHER viewing). Resolver must land on 16:30.
    llm = {"viewing_arranged": True, "viewing_datetime": "2026-08-21 16:30"}
    resolved = resolve_viewing_datetime(THREAD_45987890, llm_detection=llm, now=datetime(2026, 8, 20, 18, 0))
    assert resolved == datetime(2026, 8, 21, 16, 30)  # UK-local 4:30, not 4:00
    assert U(resolved) == datetime(2026, 8, 21, 15, 30)  # stored UTC (BST -1h)


def test_golden_45987890_regex_alone_grabs_wrong_time():
    # Documents the deterministic parser's limitation this fixture guards against:
    # with no LLM it takes the trailing 4pm. (If this ever returns 16:30 on its
    # own, great — update the comment; the combined resolver is what must be right.)
    det_only = resolve_viewing_datetime(THREAD_45987890, now=datetime(2026, 8, 20, 18, 0))
    assert det_only == datetime(2026, 8, 21, 16, 0)

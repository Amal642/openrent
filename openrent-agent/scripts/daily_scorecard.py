"""Daily lead-funnel scorecard (READ-ONLY).

One place to judge every change against: per UK day, how many first messages
went out, how many new conversations got a landlord reply, how many leads we
captured (OpenRent chat vs WhatsApp), how the WhatsApp line is converting, and
how many viewings ended with no number (cancelled, or passed uncancelled).

Usage (prod):
    venv/bin/python scripts/daily_scorecard.py            # last 7 UK days + per-account today/yesterday
    venv/bin/python scripts/daily_scorecard.py --days 14

Never writes to the database.
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func  # noqa: E402

from app.db.connection import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    Account,
    Conversation,
    Listing,
    Message,
    SearchProfile,
    WhatsAppContact,
)
from app.utils.scheduling import UK_TZ  # noqa: E402

REPLY_WINDOW = timedelta(hours=48)


# Self-contained UK-day helpers (stored timestamps are naive UTC), so this
# read-only report runs on any deployed version of the app.
def uk_today():
    return datetime.now(UK_TZ).date()


def uk_day_start_utc(day):
    return datetime.combine(day, time.min, tzinfo=UK_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_uk_date(ts):
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc).astimezone(UK_TZ).date()


def _digits10(phone):
    return re.sub(r"\D", "", phone or "")[-10:]


def collect(db, days):
    now = datetime.utcnow()
    today_uk = uk_today()
    day_list = [today_uk - timedelta(days=i) for i in range(days - 1, -1, -1)]
    start = uk_day_start_utc(day_list[0])
    wanted = set(day_list)

    def day_of(ts):
        d = utc_naive_to_uk_date(ts)
        return d if d in wanted else None

    profile_account = dict(db.query(SearchProfile.id, SearchProfile.account_id).all())
    conv_rows = (
        db.query(
            Conversation.id, Conversation.created_at, Conversation.phone_found_at,
            Conversation.extracted_phone, Conversation.our_number_shared_at,
            Conversation.cancellation_sent_at, Conversation.viewing_confirmed,
            Conversation.viewing_datetime, Conversation.viewing_cancelled,
            Listing.search_profile_id,
        )
        .join(Listing, Conversation.listing_id == Listing.id)
        .filter(
            (Conversation.created_at >= start - timedelta(days=30))
            | (Conversation.phone_found_at >= start)
            | (Conversation.cancellation_sent_at >= start)
        )
        .all()
    )
    conv_ids = [r.id for r in conv_rows]
    account_of = {r.id: profile_account.get(r.search_profile_id) for r in conv_rows}

    first_out = dict(
        db.query(Message.conversation_id, func.min(Message.created_at))
        .filter(Message.direction == "outbound", Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
        .all()
    )
    first_in = dict(
        db.query(Message.conversation_id, func.min(Message.created_at))
        .filter(Message.direction == "inbound", Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
        .all()
    )
    whatsapp_numbers = {_digits10(p) for (p,) in db.query(WhatsAppContact.phone_number)}

    fleet = defaultdict(Counter)
    per_account = defaultdict(lambda: defaultdict(Counter))

    for r in conv_rows:
        acct = account_of[r.id]
        sent_day = day_of(first_out.get(r.id))
        if sent_day:
            fleet[sent_day]["first_messages"] += 1
            per_account[sent_day][acct]["first_messages"] += 1
            # Reply within 48h of OUR first message; only judged once mature.
            sent_at = first_out[r.id]
            if sent_at + REPLY_WINDOW <= now:
                fleet[sent_day]["reply_judged"] += 1
                per_account[sent_day][acct]["reply_judged"] += 1
                replied_at = first_in.get(r.id)
                if replied_at is not None and replied_at - sent_at <= REPLY_WINDOW:
                    fleet[sent_day]["replied"] += 1
                    per_account[sent_day][acct]["replied"] += 1
        lead_day = day_of(r.phone_found_at)
        if lead_day:
            source = "lead_whatsapp" if _digits10(r.extracted_phone) in whatsapp_numbers else "lead_chat"
            fleet[lead_day][source] += 1
            per_account[lead_day][acct][source] += 1
        share_day = day_of(r.our_number_shared_at)
        if share_day:
            fleet[share_day]["number_shared"] += 1
        cancel_day = day_of(r.cancellation_sent_at)
        if cancel_day and not r.extracted_phone:
            fleet[cancel_day]["cancelled_no_number"] += 1
        vday = day_of(r.viewing_datetime)
        if (
            vday and r.viewing_confirmed and r.viewing_datetime < now
            and not r.viewing_cancelled and r.cancellation_sent_at is None
            and not r.extracted_phone
        ):
            fleet[vday]["passed_uncancelled_no_number"] += 1

    for c in db.query(WhatsAppContact).filter(WhatsAppContact.created_at >= start).all():
        d = day_of(c.created_at)
        if d:
            fleet[d]["whatsapp_contacts"] += 1
            if c.match_status == "MATCHED":
                fleet[d]["whatsapp_matched"] += 1

    return day_list, fleet, per_account


def _pct(num, den):
    return f"{100 * num / den:3.0f}%" if den else "  - "


def render(db, day_list, fleet, per_account):
    print("UK day       sent  reply%(n)   leads chat/WA  shared  WA in/matched  cancelled-no#  passed-no#")
    for d in day_list:
        f = fleet[d]
        leads = f["lead_chat"] + f["lead_whatsapp"]
        print(
            f"{d} {d:%a} {f['first_messages']:5}  {_pct(f['replied'], f['reply_judged'])}({f['reply_judged']:3})"
            f"   {leads:4} {f['lead_chat']:3}/{f['lead_whatsapp']:<3}  {f['number_shared']:5}"
            f"   {f['whatsapp_contacts']:4}/{f['whatsapp_matched']:<4}      {f['cancelled_no_number']:5}"
            f"        {f['passed_uncancelled_no_number']:4}"
        )
    print("(reply% = landlord replied within 48h of our first message; only conversations >48h old are judged)")

    accounts = db.query(Account).filter(Account.active == True, Account.deleted_at == None).order_by(Account.id).all()  # noqa: E711,E712
    shown = day_list[-2:]
    # Reply rate needs 48h to mature: use the latest 3 days that have judged data.
    mature = [d for d in day_list if fleet[d]["reply_judged"]][-3:]
    mature_label = f"{mature[0]:%d}-{mature[-1]:%d %b}" if mature else "n/a"
    print(
        f"\nper account          reply%(n) {mature_label} "
        + "".join(f"| {d:%a %d}: sent leads " for d in shown)
    )
    for a in accounts:
        judged = sum(per_account[d][a.id]["reply_judged"] for d in mature)
        replied = sum(per_account[d][a.id]["replied"] for d in mature)
        line = f"{a.id:<3} {(a.persona_name or '')[:10]:10} {'BENCHED' if a.failed else '':7} {_pct(replied, judged)}({judged:3})      "
        for d in shown:
            c = per_account[d][a.id]
            line += f"|        {c['first_messages']:4} {c['lead_chat'] + c['lead_whatsapp']:4} "
        print(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    db = SessionLocal()
    try:
        day_list, fleet, per_account = collect(db, args.days)
        render(db, day_list, fleet, per_account)
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()

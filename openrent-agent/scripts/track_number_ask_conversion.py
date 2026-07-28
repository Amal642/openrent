"""Track landlord number-ask conversion around the travel-line wording change.

Metric: when WE ask a landlord for their number (conversation.phone_requested_at
is set), how often do we actually capture it (conversation.phone_found)?

This isolates the persuasiveness of the ask itself, independent of message
wording, so we can see whether dropping the canned "4-5 hours from Bristol"
distance claim (deployed 2026-07-28) moved the share rate.

Usage:
    venv/bin/python scripts/track_number_ask_conversion.py [CUTOFF_ISO]

CUTOFF_ISO defaults to the wording-change deploy time. Everything with
phone_requested_at before the cutoff is "BEFORE", at/after is "AFTER".

Caveat: recently-asked conversations may not have converted yet (a landlord
can share a number days later), so the most recent AFTER window understates
the true rate until it matures. Re-run over time.
"""
import sys
from datetime import datetime, timezone

import psycopg2

DEPLOY_CUTOFF = "2026-07-28 13:40:00+00"


def _database_url():
    for line in open(".env"):
        if line.startswith("DATABASE_URL"):
            return line.strip().split("=", 1)[1]
    raise SystemExit("DATABASE_URL not found in .env")


def main():
    cutoff = sys.argv[1] if len(sys.argv) > 1 else DEPLOY_CUTOFF
    conn = psycopg2.connect(_database_url())
    cur = conn.cursor()

    def q(sql, params=None):
        cur.execute(sql, params or {})
        return cur.fetchall()

    now = q("select now()")[0][0]
    print(f"server now: {now}")
    print(f"wording-change cutoff: {cutoff}")
    print()

    print("=== ask -> capture by week (phone_requested_at) ===")
    for wk, n, g in q(
        """
        select date_trunc('week', phone_requested_at)::date wk,
               count(*), sum(case when phone_found then 1 else 0 end)
        from conversations
        where phone_requested_at is not null
        group by 1 order by 1
        """
    ):
        rate = 100 * g / n if n else 0
        print(f"  {wk}  asked={n:4}  captured={g:4}  {rate:4.0f}%")

    print()
    print("=== BEFORE vs AFTER wording change ===")
    for label, cond in [
        ("BEFORE", "phone_requested_at < %(cutoff)s"),
        ("AFTER ", "phone_requested_at >= %(cutoff)s"),
    ]:
        row = q(
            f"""
            select count(*) asked,
                   sum(case when phone_found then 1 else 0 end) captured,
                   sum(case when viewing_cancelled then 1 else 0 end) cancelled
            from conversations
            where phone_requested_at is not null and {cond}
            """,
            {"cutoff": cutoff},
        )[0]
        asked, captured, cancelled = (row[0] or 0), (row[1] or 0), (row[2] or 0)
        rate = 100 * captured / asked if asked else 0
        crate = 100 * cancelled / asked if asked else 0
        print(
            f"  {label}: asked={asked:4}  captured={captured:4} ({rate:4.0f}%)"
            f"   viewing_cancelled={cancelled} ({crate:.0f}%)"
        )

    print()
    print("Note: AFTER matures over time; recent asks may not have converted yet.")
    conn.close()


if __name__ == "__main__":
    main()

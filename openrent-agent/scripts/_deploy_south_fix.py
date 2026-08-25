"""One-shot deploy: apply the South-London degraded-account bench fix to prod
files via exact-string replacement, preserving unrelated hot-edits.

Aborts without writing anything if any anchor is not found exactly once.
"""
import io
import sys
import time

EDITS = [
    (
        "app/services/failed_account_detector.py",
        """async def _run_detector_cycle():
    from app.db.repository import detect_and_mark_failed_accounts

    await asyncio.to_thread(detect_and_mark_failed_accounts)
    logger.info("Failed account detection cycle complete")""",
        """async def _run_detector_cycle():
    from app.db.repository import (
        detect_and_mark_degraded_accounts,
        detect_and_mark_failed_accounts,
    )

    await asyncio.to_thread(detect_and_mark_failed_accounts)
    await asyncio.to_thread(detect_and_mark_degraded_accounts)
    logger.info("Failed account detection cycle complete")""",
    ),
    (
        "app/services/account_scheduler.py",
        """        permanently_failed_val = bool(getattr(account, "permanently_failed", False))
        cooldown_until = getattr(account, "cooldown_until", None)""",
        """        permanently_failed_val = bool(getattr(account, "permanently_failed", False))
        failed_val = bool(getattr(account, "failed", False))
        cooldown_until = getattr(account, "cooldown_until", None)""",
    ),
    (
        "app/services/account_scheduler.py",
        """        skip_reason = None
        if permanently_failed_val:
            skip_reason = "PERMANENT_FAILURE"
        elif session_status_val == "login_failed" and login_failures >= 5:""",
        """        skip_reason = None
        if permanently_failed_val:
            skip_reason = "PERMANENT_FAILURE"
        elif failed_val:
            # A failed flag (set by the outcome-based detectors, or manually)
            # benches the account: keep it out of rotation so it stops
            # consuming listing inventory until an operator clears it.
            skip_reason = "MARKED_FAILED"
        elif session_status_val == "login_failed" and login_failures >= 5:""",
    ),
    (
        "app/services/account_scheduler.py",
        """            f"proxy_healthy={proxy_healthy} "
            f"permanently_failed={permanently_failed_val} "
            f"eligible={eligible} \"""",
        """            f"proxy_healthy={proxy_healthy} "
            f"permanently_failed={permanently_failed_val} "
            f"failed={failed_val} "
            f"eligible={eligible} \"""",
    ),
    (
        "app/db/repository.py",
        '''            if replies == 0:
                account.failed = True
                account.failed_at = datetime.utcnow()
                account.failure_reason = (
                    f"No landlord replies received after 2 consecutive days of outreach "
                    f"({sent_day1} messages on day 1, {sent_day0} messages on day 2)."
                )

        db.commit()''',
        '''            if replies == 0:
                account.failed = True
                account.failed_at = datetime.utcnow()
                account.failure_reason = (
                    f"No landlord replies received after 2 consecutive days of outreach "
                    f"({sent_day1} messages on day 1, {sent_day0} messages on day 2)."
                )

        db.commit()


# Degradation / soft-ban detection.
#
# The zero-reply detector above only catches a TOTAL collapse (0 inbound over
# two days). OpenRent soft-bans present earlier and subtler: the account still
# logs in, still sends, and still receives SOME replies — but its landlord
# reply rate falls far below the healthy fleet (which sits at 60-90%) and phone
# capture drops to ~0. Such accounts keep consuming listing inventory while
# converting almost nothing, dragging a whole region's numbers down (this is
# exactly what happened to the older South-London cohort in Jul-Aug 2026).
#
# Because a flagged account is now benched by the scheduler, the thresholds are
# deliberately conservative to avoid benching a merely-slow account: judged only
# over a rolling window, only above a minimum conversation volume, and only when
# BOTH reply rate and phone capture are low (an account that gets replies but
# doesn't close is a prompt problem, not a dead account — leave it running).
DEGRADED_WINDOW_DAYS = 7
DEGRADED_MIN_CONVERSATIONS = 20
DEGRADED_MAX_REPLY_RATE = 0.35
DEGRADED_MAX_PHONE_RATE = 0.05


def detect_and_mark_degraded_accounts():
    """Bench active accounts whose landlord engagement has collapsed.

    An account is flagged failed (which the scheduler treats as a bench) when,
    over the last ``DEGRADED_WINDOW_DAYS`` days, it held at least
    ``DEGRADED_MIN_CONVERSATIONS`` conversations yet its reply rate is at or
    below ``DEGRADED_MAX_REPLY_RATE`` AND its phone-capture rate is at or below
    ``DEGRADED_MAX_PHONE_RATE`` — the signature of an OpenRent soft-ban.
    """
    from app.utils.logger import logger

    since = datetime.utcnow() - timedelta(days=DEGRADED_WINDOW_DAYS)

    with session_scope() as db:
        accounts = (
            db.query(Account)
            .filter(Account.active == True, Account.deleted_at == None)  # noqa: E711,E712
            .all()
        )

        for account in accounts:
            if account.failed:
                continue

            convos, replied, phones = (
                db.query(
                    func.count(Conversation.id),
                    func.count(Conversation.last_processed_message),
                    func.count(Conversation.extracted_phone),
                )
                .join(Listing, Conversation.listing_id == Listing.id)
                .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
                .filter(
                    SearchProfile.account_id == account.id,
                    Conversation.created_at >= since,
                )
                .one()
            )
            convos = convos or 0
            if convos < DEGRADED_MIN_CONVERSATIONS:
                continue

            reply_rate = (replied or 0) / convos
            phone_rate = (phones or 0) / convos

            if reply_rate <= DEGRADED_MAX_REPLY_RATE and phone_rate <= DEGRADED_MAX_PHONE_RATE:
                account.failed = True
                account.failed_at = datetime.utcnow()
                account.failure_reason = (
                    f"Degraded/soft-banned: over the last {DEGRADED_WINDOW_DAYS}d had "
                    f"{convos} conversations but only {round(reply_rate * 100)}% landlord "
                    f"reply rate and {round(phone_rate * 100)}% phone capture "
                    f"(healthy fleet is 60-90% reply). Benched pending review."
                )
                logger.warning(
                    "DEGRADED_ACCOUNT_BENCHED "
                    f"account_id={account.id} email={account.email} "
                    f"convos={convos} reply_rate={reply_rate:.2f} phone_rate={phone_rate:.2f}"
                )

        db.commit()''',
    ),
]


def main():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # Validate every edit first; abort before writing if anything is off.
    plans = []
    for path, old, new in EDITS:
        with io.open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if new in text and old not in text:
            print(f"SKIP (already applied): {path} :: {old[:40]!r}")
            continue
        count = text.count(old)
        if count != 1:
            print(f"ABORT: anchor found {count}x (need 1) in {path} :: {old[:60]!r}")
            sys.exit(1)
        plans.append((path, text, old, new))

    # Group edits per file so multiple replacements on one file compound.
    from collections import OrderedDict
    per_file = OrderedDict()
    for path, text, old, new in plans:
        per_file.setdefault(path, text)
        per_file[path] = per_file[path].replace(old, new, 1)

    for path, new_text in per_file.items():
        with io.open(path, "r", encoding="utf-8") as fh:
            original = fh.read()
        with io.open(f"{path}.bak-southfix-{stamp}", "w", encoding="utf-8") as fh:
            fh.write(original)
        with io.open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_text)
        print(f"PATCHED {path} (backup: {path}.bak-southfix-{stamp})")

    if not per_file:
        print("Nothing to do — all edits already present.")


if __name__ == "__main__":
    main()

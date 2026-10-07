"""Keep persona names unique across the fleet.

Landlords and OpenRent both see the profile first name; two accounts named
Katherine, or a profile renamed from Helen to Isabelle, is the kind of tell a
landlord notices ("your openrent name appears to have changed..."). Names are
set once, BEFORE the OpenRent profile is created, and never changed afterwards
(a rename is itself a tell, so clashes on live profiles are left alone).

Usage (prod, from openrent-agent/):
    PYTHONPATH=. venv/bin/python scripts/persona_names.py --check
    PYTHONPATH=. venv/bin/python scripts/persona_names.py --suggest high_earner_tech_couple
"""
import argparse
import sys
from collections import defaultdict

from app.ai.personas import PERSONA_TEMPLATES
from app.db.models import Account
from app.db.repository import session_scope


def used_names():
    """{lowercased first name: [(account_id, role, active)]} over ALL accounts,
    inactive ones included: their threads still carry the name."""
    names = defaultdict(list)
    with session_scope() as db:
        rows = db.query(
            Account.id, Account.active, Account.persona_name, Account.persona_partner_name
        ).filter(Account.deleted_at.is_(None)).all()
    for account_id, active, name, partner in rows:
        for role, value in (("tenant", name), ("partner", partner)):
            first = (value or "").strip().split(" ")[0].lower()
            if first:
                names[first].append((account_id, role, bool(active)))
    return names


def name_clashes(account_ids=None):
    """Names held by more than one account, optionally only those touching account_ids."""
    clashes = {
        name: holders for name, holders in used_names().items()
        if len({h[0] for h in holders}) > 1
    }
    if account_ids is not None:
        wanted = set(account_ids)
        clashes = {n: h for n, h in clashes.items() if wanted & {x[0] for x in h}}
    return clashes


def free_names(persona_type):
    template = PERSONA_TEMPLATES[persona_type]
    taken = set(used_names())
    return (
        [n for n in template["names"]["primary"] if n.lower() not in taken],
        [n for n in template["names"]["partner"] if n.lower() not in taken],
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="list names used by more than one account")
    parser.add_argument("--suggest", metavar="PERSONA_TYPE", choices=sorted(PERSONA_TEMPLATES))
    args = parser.parse_args(argv)

    if args.suggest:
        primary, partner = free_names(args.suggest)
        print(f"free tenant names:  {', '.join(primary) or '(pool exhausted, add names)'}")
        print(f"free partner names: {', '.join(partner) or '(pool exhausted, add names)'}")
    if args.check or not args.suggest:
        clashes = name_clashes()
        if not clashes:
            print("no clashes")
        for name, holders in sorted(clashes.items()):
            desc = ", ".join(f"{a} {role}{'' if active else ' (inactive)'}" for a, role, active in holders)
            print(f"CLASH {name}: {desc}")
        return 1 if clashes and args.check else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

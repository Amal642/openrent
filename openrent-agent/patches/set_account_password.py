"""Set the OpenRent password on one or more accounts without it touching argv,
shell history or logs: it is read with getpass from the terminal.

Usage (on prod, interactive ssh -t):
    PYTHONPATH=. venv/bin/python patches/set_account_password.py 39 40 41

Does NOT activate the accounts; it only stores the password (encrypted by the
model's EncryptedString column) and resets session_auth_failures.
"""
import getpass
import sys

from app.db.models import Account
from app.db.repository import session_scope


def main(ids):
    if not ids:
        sys.exit("usage: set_account_password.py <account_id> [<account_id> ...]")
    with session_scope() as s:
        rows = s.query(Account).filter(Account.id.in_(ids)).order_by(Account.id).all()
        found = {a.id for a in rows}
        missing = [i for i in ids if i not in found]
        if missing:
            sys.exit(f"accounts not found: {missing}")
        for a in rows:
            print(f"  {a.id}  {a.email}")

    pw = getpass.getpass("OpenRent password for these accounts: ")
    if not pw or pw != getpass.getpass("Repeat password: "):
        sys.exit("passwords empty or did not match; nothing changed")

    with session_scope() as s:
        for a in s.query(Account).filter(Account.id.in_(ids)).all():
            a.password = pw
            a.session_auth_failures = 0
        s.commit()

    with session_scope() as s:
        for a in s.query(Account).filter(Account.id.in_(ids)).order_by(Account.id).all():
            ok = a.password == pw
            print(f"  {a.id}  password {'SET' if ok else 'NOT SET'}  active={a.active}")


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]])

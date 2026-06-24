"""
One-time migration: encrypt all plaintext passwords already stored in the DB.

Run ONCE after adding FIELD_ENCRYPTION_KEY to your .env file:
    python scripts/encrypt_passwords.py

Safe to run multiple times — values already prefixed with "enc:" are skipped.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app.db.connection import SessionLocal
from app.utils.crypto import encrypt, is_encrypted


def migrate():
    db = SessionLocal()
    accounts_updated = 0
    proxies_updated = 0

    try:
        # --- accounts table ---
        from sqlalchemy import text

        rows = db.execute(text("SELECT id, password, proxy_password FROM accounts")).fetchall()
        for row in rows:
            acc_id, pwd, proxy_pwd = row

            new_pwd = None
            new_proxy_pwd = None

            if pwd and not is_encrypted(pwd):
                new_pwd = encrypt(pwd)

            if proxy_pwd and not is_encrypted(proxy_pwd):
                new_proxy_pwd = encrypt(proxy_pwd)

            if new_pwd or new_proxy_pwd:
                updates = []
                params = {"id": acc_id}
                if new_pwd:
                    updates.append("password = :pwd")
                    params["pwd"] = new_pwd
                if new_proxy_pwd:
                    updates.append("proxy_password = :proxy_pwd")
                    params["proxy_pwd"] = new_proxy_pwd
                db.execute(
                    text(f"UPDATE accounts SET {', '.join(updates)} WHERE id = :id"),
                    params,
                )
                accounts_updated += 1

        # --- proxies table ---
        rows = db.execute(text("SELECT id, password FROM proxies")).fetchall()
        for row in rows:
            proxy_id, pwd = row
            if pwd and not is_encrypted(pwd):
                db.execute(
                    text("UPDATE proxies SET password = :pwd WHERE id = :id"),
                    {"pwd": encrypt(pwd), "id": proxy_id},
                )
                proxies_updated += 1

        db.commit()
        print(f"Done. Encrypted {accounts_updated} account rows, {proxies_updated} proxy rows.")

    except Exception as exc:
        db.rollback()
        print(f"Migration failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()

"""
Export decrypted account credentials to a text file.

Run from openrent-agent/:
    python scripts/export_credentials.py

Output: credentials_export.txt  (created in the current directory)
The file is overwritten each time you run the script.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.db.connection import SessionLocal
from app.utils.crypto import decrypt


def export():
    db = SessionLocal()
    try:
        accounts = db.execute(
            text("SELECT id, email, password, proxy_password FROM accounts ORDER BY id")
        ).fetchall()

        proxies = db.execute(
            text("SELECT id, name, host, port, username, password FROM proxies ORDER BY id")
        ).fetchall()
    finally:
        db.close()

    lines = []
    lines.append("=" * 60)
    lines.append("CREDENTIAL EXPORT")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("=" * 60)

    lines.append("")
    lines.append("ACCOUNTS")
    lines.append("-" * 60)

    for row in accounts:
        acc_id, email, pwd, proxy_pwd = row
        plain_pwd = decrypt(pwd) if pwd else ""
        plain_proxy_pwd = decrypt(proxy_pwd) if proxy_pwd else ""

        lines.append(f"ID            : {acc_id}")
        lines.append(f"Email         : {email}")
        lines.append(f"Password      : {plain_pwd}")
        if plain_proxy_pwd:
            lines.append(f"Proxy Password: {plain_proxy_pwd}")
        lines.append("")

    lines.append("PROXIES")
    lines.append("-" * 60)

    for row in proxies:
        proxy_id, name, host, port, username, pwd = row
        plain_pwd = decrypt(pwd) if pwd else ""

        lines.append(f"ID       : {proxy_id}")
        lines.append(f"Name     : {name}")
        lines.append(f"Host     : {host}:{port}")
        lines.append(f"Username : {username or '—'}")
        lines.append(f"Password : {plain_pwd or '—'}")
        lines.append("")

    output = "\n".join(lines)
    out_path = os.path.join(os.path.dirname(__file__), "..", "credentials_export.txt")
    out_path = os.path.abspath(out_path)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Exported {len(accounts)} account(s) and {len(proxies)} proxy record(s).")
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    export()

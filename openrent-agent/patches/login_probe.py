"""Login-only probe for freshly provisioned accounts: proxy check, real
auth.login (saves the session file so the first worker run reuses it), then
open the dashboard + enquiries pages read-only. Sends nothing.

Usage (prod): PYTHONPATH=. venv/bin/python patches/login_probe.py 39 40 41
"""
import asyncio
import sys

from app.browser.auth import _is_authenticated, login
from app.browser.launcher import get_session_file, launch_browser
from sqlalchemy.orm import joinedload

from app.db.models import Account
from app.db.repository import ensure_account_persona, session_scope
from app.proxy.check_proxy import check_proxy
from scripts.persona_names import name_clashes
from app.workers.account_worker import _proxy_url_for_account


async def probe(account):
    tag = f"[{account.id} {account.email}]"
    url = _proxy_url_for_account(account)
    if url:
        res = await asyncio.to_thread(check_proxy, url)
        print(tag, "proxy", getattr(account.proxy, "name", "?"),
              "healthy" if res.get("healthy") else f"UNHEALTHY {res.get('error')}",
              "ip", res.get("ip") or res.get("egress_ip"), "latency", res.get("latency"))
    playwright = browser = None
    try:
        playwright, browser, context, page = await launch_browser(account)
        await login(page, context, account)
        print(tag, "LOGIN OK", page.url, "session", get_session_file(account))
        for path in ("/my-dashboard", "/my-enquiries"):
            await page.goto(f"https://www.openrent.co.uk{path}", wait_until="domcontentloaded", timeout=45000)
            body = (await page.inner_text("body"))[:4000].lower()
            flags = [w for w in ("verify your", "suspended", "restricted", "phone number", "human verification", "captcha") if w in body]
            print(tag, path, "->", page.url, "| title", repr(await page.title())[:60], "| flags", flags or "-")
        print(tag, "still authenticated:", await _is_authenticated(page))
    except Exception as exc:
        print(tag, "LOGIN FAILED:", type(exc).__name__, str(exc)[:300])
    finally:
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


async def main(ids):
    # Loaded by id regardless of `active`, so a paused account can be probed
    # before it is switched back on.
    with session_scope() as db:
        accounts = {
            a.id: a
            for a in db.query(Account).options(joinedload(Account.proxy)).filter(Account.id.in_(ids)).all()
        }
    for i in ids:
        if i not in accounts:
            print(f"[{i}] no such account; skipped")
            continue
        ensure_account_persona(i)
        await probe(accounts[i])
    # Names go on the OpenRent profile once and are never renamed, so a clash
    # must be caught here, before the account starts messaging.
    for name, holders in sorted(name_clashes(ids).items()):
        print(f"PERSONA_NAME_CLASH {name}: " + ", ".join(f"acct {a} {role}" for a, role, _ in holders))


if __name__ == "__main__":
    asyncio.run(main([int(x) for x in sys.argv[1:]]))

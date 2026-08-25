"""One-off: accelerate agent-cache recovery for high-supply South areas.

Re-scans agent-flagged landlords (is_agent=true, property_count<=20, cache
invalidated) that own agent-skipped listings in the target South areas, using
the NEW available-only get_landlord_property_count. Landlords that flip to
non-agent get their agent-skipped listings' skip_reason cleared so the fleet
re-claims and contacts them. Idempotent: only touches landlords whose cache is
still NULL, so re-running resumes.
"""
import asyncio, re, sys
from app.db.connection import SessionLocal
from app.db.models import Account, Landlord, Listing, SearchProfile
from app.browser.launcher import launch_browser
from app.openrent.landlords import get_landlord_property_count
from app.db.repository import update_landlord_scan
from sqlalchemy import text

AREAS=["Clapham, London","Lewisham, London","Woolwich, Greater London","Wandsworth, London",
       "Peckham, London","Bexleyheath, Greater London","Upper Norwood, London","Greenwich, London",
       "Hanworth, London","Bermondsey, London","Morden, London","Croydon, Greater London"]
SCRAPER_ACCOUNT_ID=34

def log(m):
    print(m, flush=True)

async def main():
    s=SessionLocal()
    rows=s.execute(text("""
        SELECT DISTINCT ld.id, ld.profile_url
        FROM landlords ld
        JOIN listings l ON l.landlord_id=ld.id
        JOIN search_profiles sp ON l.search_profile_id=sp.id
        WHERE sp.location IN :areas AND l.skip_reason='agent'
          AND ld.is_agent=true AND ld.property_count<=20 AND ld.last_checked_at IS NULL
    """).bindparams(__import__("sqlalchemy").bindparam("areas", expanding=True)),
        {"areas":AREAS}).fetchall()
    log(f"landlords to rescan: {len(rows)}")
    acct=s.query(Account).filter(Account.id==SCRAPER_ACCOUNT_ID).first()

    pw=browser=context=None
    rescanned=flipped=still_agent=errors=listings_freed=0
    try:
        pw,browser,context,page=await launch_browser(acct)
        for i,(lid, profile_url) in enumerate(rows, 1):
            landlord_num=profile_url.rsplit("/",1)[-1]
            try:
                available=await get_landlord_property_count(page, landlord_num)
            except Exception as e:
                errors+=1; log(f"[{i}/{len(rows)}] ld={landlord_num} ERROR {str(e)[:60]}"); continue
            is_agent = available>3
            update_landlord_scan(profile_url, available, is_agent)
            rescanned+=1
            if not is_agent:
                flipped+=1
                res=s.execute(text("""
                    UPDATE listings SET skip_reason=NULL, processing_owner=NULL, processing_started_at=NULL
                    WHERE landlord_id=:lid AND skip_reason='agent'
                      AND message_sent=false AND coalesce(listing_archived,false)=false
                """), {"lid":lid})
                s.commit()
                listings_freed+=res.rowcount
                log(f"[{i}/{len(rows)}] ld={landlord_num} avail={available} -> LANDLORD, freed {res.rowcount} listings")
            else:
                still_agent+=1
                log(f"[{i}/{len(rows)}] ld={landlord_num} avail={available} -> agent (kept)")
    finally:
        for x in (context,browser):
            try:
                if x: await x.close()
            except: pass
        try:
            if pw: await pw.stop()
        except: pass
    log(f"DONE rescanned={rescanned} flipped_to_landlord={flipped} still_agent={still_agent} errors={errors} listings_freed={listings_freed}")

asyncio.run(main())

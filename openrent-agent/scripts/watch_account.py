import sys
from datetime import datetime, timedelta
from app.db.connection import SessionLocal
from app.db import models as m
from sqlalchemy import func, cast, Date
EMAIL = sys.argv[1] if len(sys.argv)>1 else "silverwind2026@outlook.com"
DAYS = int(sys.argv[2]) if len(sys.argv)>2 else 12
s=SessionLocal()
M=m.Message; C=m.Conversation; A=m.Account; L=m.Listing; SP=m.SearchProfile
acc=s.query(A).filter(A.email==EMAIL).first()
cids=s.query(C.id).join(L,C.listing_id==L.id).join(SP,L.search_profile_id==SP.id).filter(SP.account_id==acc.id).subquery()
idq=s.query(cids.c.id)
since=datetime.utcnow().date()-timedelta(days=DAYS)
out=dict(s.query(cast(M.created_at,Date),func.count()).filter(M.direction=='outbound',M.conversation_id.in_(idq),cast(M.created_at,Date)>=since).group_by(cast(M.created_at,Date)).all())
inb=dict(s.query(cast(M.created_at,Date),func.count()).filter(M.direction=='inbound',M.conversation_id.in_(idq),cast(M.created_at,Date)>=since).group_by(cast(M.created_at,Date)).all())
last_in=s.query(func.max(M.created_at)).filter(M.direction=='inbound',M.conversation_id.in_(idq)).scalar()
now=datetime.utcnow()
print(f"=== {EMAIL}  (as of {now:%Y-%m-%d %H:%M} UTC) ===")
print(f"active={acc.active} failed={acc.failed} session={acc.session_status} worker={acc.worker_status}")
print(f"last reply: {last_in}  ({(now-last_in).total_seconds()/86400:.1f} days ago)")
print(f"{'date':12} {'sent':>5} {'recv':>5}")
d=since
while d<=now.date():
    print(f"{str(d):12} {out.get(d,0):5} {inb.get(d,0):5}")
    d+=timedelta(days=1)
# rolling verdict hint
recent_sent=sum(c for dd,c in out.items() if dd> now.date()-timedelta(days=4))
recent_recv=sum(c for dd,c in inb.items() if dd> now.date()-timedelta(days=4))
print(f"\nlast 4 days: sent={recent_sent} recv={recent_recv}")
if recent_sent>=20 and recent_recv==0:
    print("VERDICT HINT: 20+ sends, 0 replies over 4d -> degradation likely real; consider retiring.")
else:
    print("VERDICT HINT: inconclusive / still receiving or small sample -> keep watching.")
s.close()

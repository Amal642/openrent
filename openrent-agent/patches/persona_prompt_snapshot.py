"""Fingerprint every account's surname + human reply prompt (fixed conversation)
so a deploy can prove legacy accounts are byte-identical before/after.
Usage: PYTHONPATH=. venv/bin/python patches/persona_prompt_snapshot.py out.json"""
import hashlib, json, sys
import app.ai.prompts as _prompts
from app.ai.prompts import build_human_renter_reply_prompt, persona_surnames

# Prompts embed the current UK time; freeze it so runs are comparable.
_prompts.current_uk_datetime_line = lambda: "Monday 5 October 2026, 12:00"
from app.db.models import Account
from app.db.repository import ensure_account_persona, session_scope

CONVS = [
    "LANDLORD: Hi, what are your full names please?",
    "LANDLORD: Can you send me your email for the referencing form?",
]
with session_scope() as s:
    ids = [a.id for a in s.query(Account).order_by(Account.id)]
out = {}
for i in ids:
    p = ensure_account_persona(i)
    out[i] = {
        "surnames": persona_surnames(p),
        "prompts": [hashlib.md5(build_human_renter_reply_prompt(conversation=c, persona=p).encode()).hexdigest() for c in CONVS],
    }
json.dump(out, open(sys.argv[1], "w"), indent=1, sort_keys=True)
print(len(out), "accounts fingerprinted")

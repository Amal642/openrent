import json
import psycopg2
import os

conn = psycopg2.connect('postgresql://postgres:LgzddSO14cprgC1N@db.nukqzdeshnuwdsxfexcv.supabase.co:5432/postgres')
cur = conn.cursor()
cur.execute('SELECT id, email, persona_name, persona_partner_name FROM accounts WHERE active = TRUE ORDER BY id')
accounts = {r[0]: {'email': r[1], 'persona_name': r[2], 'partner_name': r[3]} for r in cur.fetchall()}
conn.close()

session_dir = '/opt/openrent-agent/openrent-agent/sessions'

for acc_id, acc in accounts.items():
    path = os.path.join(session_dir, 'account_{}.json'.format(acc_id))
    if not os.path.exists(path):
        print('Acct {} | {} | NO SESSION FILE'.format(acc_id, acc['email']))
        continue

    with open(path) as f:
        data = json.load(f)

    display_name = None
    for origin in data.get('origins', []):
        for item in origin.get('localStorage', []):
            if item.get('name') == 'chooserAccounts':
                try:
                    parsed = json.loads(item['value'])
                    if isinstance(parsed, list) and parsed:
                        display_name = parsed[0].get('displayName')
                except Exception:
                    pass

    persona = acc['persona_name']
    partner = acc['partner_name']
    match = 'OK' if display_name and display_name.lower() == (persona or '').lower() else 'MISMATCH'
    print('Acct {} | DB sender: {:10} | DB partner: {:10} | OpenRent: {:10} | {}'.format(
        acc_id, persona, partner, display_name, match))

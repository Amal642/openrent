import psycopg2
import re

conn = psycopg2.connect('postgresql://postgres:LgzddSO14cprgC1N@db.nukqzdeshnuwdsxfexcv.supabase.co:5432/postgres')
cur = conn.cursor()

ACCOUNT_ID = 13
NAME = 'Alex'

# Get all active conversations for account 13
cur.execute("""
    SELECT c.id, c.status, c.thread_id
    FROM conversations c
    JOIN listings l ON c.listing_id = l.id
    JOIN search_profiles sp ON l.search_profile_id = sp.id
    WHERE sp.account_id = %s
    AND c.status NOT IN ('CLOSED', 'REJECTED', 'BLOCKED', 'VIEWING_CANCELLED')
    ORDER BY c.last_message_at DESC
""", (ACCOUNT_ID,))
convos = cur.fetchall()
print('Active conversations: %d' % len(convos))
print()

name_exposed = []
name_clean = []

for convo_id, status, thread_id in convos:
    cur.execute("""
        SELECT direction, content, created_at
        FROM messages
        WHERE conversation_id = %s
        ORDER BY created_at ASC
    """, (convo_id,))
    messages = cur.fetchall()

    exposed = False
    for direction, content, created_at in messages:
        if direction not in ('outbound', 'ai', 'user'):
            continue
        # Only check outbound messages (what we sent)
        if direction not in ('outbound', 'ai'):
            continue
        content_str = content or ''
        # Check for name mention (case-insensitive, word boundary)
        if re.search(r'\b' + re.escape(NAME) + r'\b', content_str, re.IGNORECASE):
            exposed = True
            snippet = content_str[:120].replace('\n', ' ')
            print('EXPOSED  convo=%s status=%s thread=%s' % (convo_id, status, thread_id))
            print('  msg: %r' % snippet)
            break

    if exposed:
        name_exposed.append(convo_id)
    else:
        name_clean.append(convo_id)
        print('CLEAN    convo=%s status=%s thread=%s' % (convo_id, status, thread_id))

print()
print('Summary: %d exposed, %d clean' % (len(name_exposed), len(name_clean)))
if name_exposed:
    print('Exposed convo IDs: %s' % name_exposed)

conn.close()

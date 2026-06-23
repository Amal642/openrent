import psycopg2

conn = psycopg2.connect('postgresql://postgres:LgzddSO14cprgC1N@db.nukqzdeshnuwdsxfexcv.supabase.co:5432/postgres')
cur = conn.cursor()

for acc_id in [12, 13]:
    cur.execute("""
        SELECT a.id, a.email, a.persona_name, a.persona_partner_name
        FROM accounts a WHERE a.id = %s
    """, (acc_id,))
    row = cur.fetchone()
    if row:
        print('Acct %s (%s): sender=%r partner=%r' % (row[0], row[1], row[2], row[3]))

    cur.execute("""
        SELECT c.status, COUNT(*)
        FROM conversations c
        JOIN search_profiles sp ON c.search_profile_id = sp.id
        WHERE sp.account_id = %s
        GROUP BY c.status ORDER BY COUNT(*) DESC
    """, (acc_id,))
    for r in cur.fetchall():
        print('  %s: %s' % (r[0], r[1]))

    cur.execute("""
        SELECT c.id, c.status, c.last_message_at,
               (SELECT m.content FROM messages m WHERE m.conversation_id = c.id AND m.direction = 'outbound' ORDER BY m.created_at LIMIT 1) as first_msg
        FROM conversations c
        JOIN search_profiles sp ON c.search_profile_id = sp.id
        WHERE sp.account_id = %s AND c.status NOT IN ('CLOSED','REJECTED','BLOCKED')
        ORDER BY c.last_message_at DESC LIMIT 5
    """, (acc_id,))
    print('  Recent live convos:')
    for r in cur.fetchall():
        snippet = (r[3] or '')[:80].replace('\n', ' ')
        print('    id=%s status=%s last=%s msg=%r' % (r[0], r[1], r[2], snippet))

conn.close()

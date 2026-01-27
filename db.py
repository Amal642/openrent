import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Admin@123",
    "database": "openrent"
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def conversation_exists(thread_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT 1 FROM conversations WHERE thread_id=%s", (thread_id,))
    result = cursor.fetchone()
    db.close()
    return result is not None

def insert_conversation(thread_id, property_url):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT IGNORE INTO conversations (thread_id, property_url)
        VALUES (%s, %s)
    """, (thread_id, property_url))
    db.commit()
    db.close()

def mark_replied(thread_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE conversations SET replied=TRUE WHERE thread_id=%s
    """, (thread_id,))
    db.commit()
    db.close()

def close_with_phone(thread_id, phone):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE conversations 
        SET phone_number=%s, status='closed'
        WHERE thread_id=%s
    """, (phone, thread_id))
    db.commit()
    db.close()

def is_closed(thread_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT status FROM conversations WHERE thread_id=%s
    """, (thread_id,))
    row = cursor.fetchone()
    db.close()
    return row and row[0] == 'closed'

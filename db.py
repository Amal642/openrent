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
        INSERT INTO conversations (thread_id, property_url, status)
        VALUES (%s, %s, 'sent')
    """, (thread_id, property_url))
    db.commit()
    db.close()

def update_phone_and_status(thread_id, phone):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE conversations 
        SET phone_number=%s, status='number_received', last_message_at=NOW()
        WHERE thread_id=%s
    """, (phone, thread_id))
    db.commit()
    db.close()

def get_conversation(thread_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM conversations WHERE thread_id=%s", (thread_id,))
    result = cursor.fetchone()
    db.close()
    return result

def insert_with_phone(thread_id, phone):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO conversations (thread_id, phone_number, status, last_message_at)
        VALUES (%s, %s, 'number_received', NOW())
    """, (thread_id, phone))
    db.commit()
    db.close()



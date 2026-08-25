import sys
import os
from pathlib import Path
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CRM_USERNAME", "test-admin")
os.environ.setdefault("CRM_PASSWORD_HASH", generate_password_hash("test-password"))
os.environ.setdefault("CRM_AUTH_SECRET", "test-auth-secret")
# Field-level encryption (EncryptedString columns: Account.password,
# Proxy.proxy_password) needs a valid Fernet key. Tests only round-trip within
# the process, so a session-local key is fine. setdefault preserves a real key
# if one is already exported (e.g. running against a configured environment).
os.environ.setdefault("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())

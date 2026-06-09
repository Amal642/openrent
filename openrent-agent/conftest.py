import sys
import os
from pathlib import Path
from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CRM_USERNAME", "test-admin")
os.environ.setdefault("CRM_PASSWORD_HASH", generate_password_hash("test-password"))
os.environ.setdefault("CRM_AUTH_SECRET", "test-auth-secret")

from app.db.repository import (
    create_account,
    create_search_profile
)
from app.config import settings
import os



# Create account
account = create_account(
    email=os.getenv("EMAIL"),
    password=os.getenv("PASSWORD"),
    session_file="sessions/account_1.json"
)

# Create search profile
create_search_profile(
    account_id=account.id,
    location="London",
    price_min=500,
    price_max=800,
    bedrooms_min=2,
    bedrooms_max=4,
    pets_allowed=True
)

print("Seed data created")
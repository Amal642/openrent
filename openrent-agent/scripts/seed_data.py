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
    session_file="sessions/account_1.json",


    initial_message="""Hi, I’m Mary, I work in IT. My husband and I really like your property and were hoping to have a quick call before booking a viewing.
Could you please share your phone number?
Thanks so much!"""
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
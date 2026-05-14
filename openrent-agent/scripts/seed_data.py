from app.db.repository import (
    create_account,
    create_search_profile
)
from app.config import settings
import os

# ---------------- ACCOUNT 1 ----------------

# Create account
account_1 = create_account(
    email=os.getenv("EMAIL_1"),
    password=os.getenv("PASSWORD_1"),
    session_file="sessions/account_1.json",
    # mobile_number=os.getenv("MOBILE_1"),

    initial_message="""Hi, I’m Mary, I work in IT. My husband and I really like your property and were hoping to have a quick call before booking a viewing.
Could you please share your phone number?
Thanks so much!"""

)

# Create search profile
create_search_profile(
    account_id=account_1.id,
    location="buckingham palace greater london",
    price_min=500,
    price_max=800,
    bedrooms_min=2,
    bedrooms_max=4,
    area=10,
    pets_allowed=True
)

# ---------------- ACCOUNT 2 ----------------

# account_2 = create_account(
#     email=os.getenv("EMAIL_2"),
#     password=os.getenv("PASSWORD_2"),
#     mobile_number=os.getenv("MOBILE_2"),

#     session_file="sessions/account_2.json",

#     initial_message="Hello..."
# )

# create_search_profile(
#     account_id=account_2.id,

#     location="London",

#     area=5,

#     price_min=700,
#     price_max=1500,

#     bedrooms_min=2,
#     bedrooms_max=3,

#     pets_allowed=False
# )

print("Seed data created")
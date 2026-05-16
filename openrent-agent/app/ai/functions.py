import random


HIGH_STATUS_JOBS = [
    "Software Engineer",
    "AI Engineer",
    "Cybersecurity Specialist",
    "Data Scientist",
    "Cloud Architect",
    "DevOps Engineer",
    "Doctor",
    "Surgeon",
    "Dentist",
    "Cardiologist",
    "Investment Banker",
    "Chartered Accountant",
    "Pilot",
    "Architect",
    "Mechanical Engineer",
    "Civil Engineer",
    "Electrical Engineer",
    "Product Manager",
    "Business Consultant",
    "University Professor",
    "Pharmacist",
    "Entrepreneur",
    "Real Estate Developer"
]


def get_random_job():
    return random.choice(HIGH_STATUS_JOBS)


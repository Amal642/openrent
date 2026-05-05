import re

def extract_phone(text):
    text = text.replace(" ", "")
    match = re.search(r'(07\d{9}|\+447\d{9})', text)
    return match.group(0) if match else None

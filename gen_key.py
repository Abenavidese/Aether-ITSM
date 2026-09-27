"""Appends a fresh Fernet ENCRYPTION_KEY to .env (never to .env.example)."""
from cryptography.fernet import Fernet

key = Fernet.generate_key().decode("utf-8")
with open(".env", "a", encoding="utf-8") as f:
    f.write(f'\nENCRYPTION_KEY="{key}"\n')
print("ENCRYPTION_KEY appended to .env")

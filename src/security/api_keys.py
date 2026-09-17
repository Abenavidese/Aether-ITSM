"""
Webhook API key generation and verification.

The raw key is never stored. We keep a one-way SHA-256 digest for O(1)
lookup/verification (so a DB leak alone never yields a usable credential),
and separately an encrypted (Fernet) copy so the tenant's own settings page
can redisplay it to them — the same tenant that already knows the key.
"""
import hashlib
import secrets

API_KEY_PREFIX = "aeth_live_"


def generate_api_key() -> str:
    """Generates a new high-entropy webhook API key for a tenant."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """One-way digest used to verify a presented key without ever storing it in plaintext."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

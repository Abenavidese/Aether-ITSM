import base64
import hashlib
from cryptography.fernet import Fernet
from src.config import get_settings

def _get_fernet() -> Fernet:
    """
    Returns a Fernet instance using the application's encryption key.
    """
    key = get_settings().encryption_key.encode('utf-8')
    return Fernet(key)

def encrypt_token(token: str | None) -> str | None:
    """Encrypts a plaintext token for storage."""
    if not token or token == "MASKED":
        return token
    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(token.encode('utf-8'))
    return encrypted_bytes.decode('utf-8')

def decrypt_token(encrypted_token: str | None) -> str | None:
    """Decrypts a token from storage."""
    if not encrypted_token:
        return encrypted_token
    try:
        fernet = _get_fernet()
        decrypted_bytes = fernet.decrypt(encrypted_token.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except Exception:
        # If decryption fails (e.g. old plaintext token), return None or raise
        # This will happen if we try to decrypt the old unencrypted token
        return None

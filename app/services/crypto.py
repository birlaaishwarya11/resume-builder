"""
Symmetric encryption for API keys stored in the database.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.
Key is read from FERNET_KEY env var. In dev, auto-generates to .fernet_key.
"""

import os

from cryptography.fernet import Fernet

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEV_KEY_FILE = os.path.join(_PROJECT_ROOT, '.fernet_key')


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the configured encryption key."""
    key = os.environ.get('FERNET_KEY', '').strip()
    if not key:
        if os.path.exists(_DEV_KEY_FILE):
            with open(_DEV_KEY_FILE, 'r') as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key().decode()
            with open(_DEV_KEY_FILE, 'w') as f:
                f.write(key)
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key. Returns a URL-safe base64 string."""
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt an API key. Returns the original plaintext string."""
    if not ciphertext:
        return ''
    return _get_fernet().decrypt(ciphertext.encode()).decode()

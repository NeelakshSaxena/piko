"""Encryption at rest for push delivery addresses (FCM tokens, Web Push endpoints and keys).

A push address is not an identity and does not authenticate anyone, but whoever holds it can send
unsolicited notifications to a child's phone or a parent's browser, so it is stored sealed with
AES-256-GCM under a key derived (HKDF) from the server's existing HMAC key. A database dump alone
therefore does not yield usable addresses.
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_NONCE_BYTES = 12


class PushSecretBox:
    def __init__(self, hmac_key: bytes) -> None:
        key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"piko-push-secret"
        ).derive(hmac_key)
        self._aes = AESGCM(key)

    def seal(self, plaintext: str, context: str) -> str:
        """`context` (for example the kind of address) is authenticated, so a sealed value cannot be
        replayed into a different column."""
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aes.encrypt(nonce, plaintext.encode(), context.encode())
        return base64.urlsafe_b64encode(nonce + sealed).decode()

    def open(self, sealed: str, context: str) -> str | None:
        """None when the value is corrupt, from another key, or for another context: fail closed."""
        try:
            raw = base64.urlsafe_b64decode(sealed.encode())
            return self._aes.decrypt(
                raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], context.encode()
            ).decode()
        except (InvalidTag, ValueError):
            return None

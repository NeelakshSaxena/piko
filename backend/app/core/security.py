"""Credential primitives: password hashing, JWTs, opaque device tokens, pairing codes.

Nothing here logs. Raw tokens and codes are returned to the caller exactly once; only keyed or
plain SHA-256 digests are persisted.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import bcrypt
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings

DEVICE_TOKEN_PREFIX = "pkd_"
ACCESS_AUDIENCE = "piko-api"
REFRESH_AUDIENCE = "piko-refresh"
PASSWORD_MAX_BYTES = 72  # bcrypt silently truncates beyond this; reject instead
UNUSABLE_PASSWORD = "!"  # stored for child identities, which can never log in
# 32 symbols, no I/O/0/1; 9 symbols = 45 bits of entropy. See ADR-009.
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_CODE_LENGTH = 9
_PAIRING_RE = re.compile(rf"^[{PAIRING_ALPHABET}]{{{PAIRING_CODE_LENGTH}}}$")


def password_is_acceptable_length(password: str) -> bool:
    return 0 < len(password.encode()) <= PASSWORD_MAX_BYTES


def hash_password(password: str, rounds: int) -> str:
    if not password_is_acceptable_length(password):
        raise ValueError("password length unacceptable")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash == UNUSABLE_PASSWORD or not password_is_acceptable_length(password):
        return False
    try:
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
    except ValueError:  # malformed hash in storage: fail closed
        return False


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def keyed_digest(key: bytes, label: str, value: str) -> str:
    """HMAC-SHA256 with domain separation, for values that need lookup but not reversal."""
    return hmac.new(key, f"{label}:{value}".encode(), hashlib.sha256).hexdigest()


def generate_rsa_private_pem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    family_hint: uuid.UUID | None  # advisory only; authorization always re-checks the database


class TokenService:
    """Issues and verifies RS256 access/refresh JWTs. Revocation is checked by the caller."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.jwt_issuer
        self._access_ttl = settings.access_ttl_seconds
        self._refresh_ttl = settings.refresh_ttl_seconds
        pem = settings.jwt_private_key_file.read_bytes()
        private = serialization.load_pem_private_key(pem, password=None)
        self._private_key = private
        self._public_key = private.public_key()

    @property
    def access_ttl(self) -> int:
        return self._access_ttl

    @property
    def refresh_ttl(self) -> int:
        return self._refresh_ttl

    def _encode(
        self, kind: str, audience: str, ttl: int, claims: TokenClaims, now: datetime
    ) -> str:
        payload = {
            "iss": self._issuer,
            "aud": audience,
            "sub": str(claims.user_id),
            "sid": str(claims.session_id),
            "typ": kind,
            "iat": now,
            "exp": now + timedelta(seconds=ttl),
            "jti": str(uuid.uuid4()),
        }
        if claims.family_hint is not None:
            payload["fam"] = str(claims.family_hint)
        return jwt.encode(payload, self._private_key, algorithm="RS256")  # type: ignore[arg-type]

    def issue_access(self, claims: TokenClaims, now: datetime | None = None) -> str:
        return self._encode("access", ACCESS_AUDIENCE, self._access_ttl, claims, now or _now())

    def issue_refresh(self, claims: TokenClaims, now: datetime | None = None) -> str:
        return self._encode("refresh", REFRESH_AUDIENCE, self._refresh_ttl, claims, now or _now())

    def verify(self, token: str, kind: Literal["access", "refresh"]) -> TokenClaims | None:
        audience = ACCESS_AUDIENCE if kind == "access" else REFRESH_AUDIENCE
        try:
            data = jwt.decode(
                token,
                self._public_key,  # type: ignore[arg-type]
                algorithms=["RS256"],
                audience=audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "sid", "typ"]},
            )
            if data["typ"] != kind:
                return None
            fam = data.get("fam")
            return TokenClaims(
                user_id=uuid.UUID(data["sub"]),
                session_id=uuid.UUID(data["sid"]),
                family_hint=uuid.UUID(fam) if fam else None,
            )
        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
            return None


def _now() -> datetime:
    return datetime.now(UTC)


def new_device_token() -> str:
    return DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)


def is_device_token(token: str) -> bool:
    return token.startswith(DEVICE_TOKEN_PREFIX)


def new_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))


def format_pairing_code(code: str) -> str:
    return "-".join(code[i : i + 3] for i in range(0, len(code), 3))


def normalize_pairing_code(raw: str) -> str | None:
    """Canonical form (upper-case, separators removed), or None if it cannot be a valid code."""
    code = re.sub(r"[\s-]", "", raw).upper()
    return code if _PAIRING_RE.fullmatch(code) else None

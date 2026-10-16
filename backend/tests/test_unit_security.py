"""Unit tests: credential primitives, settings guards, rate limiter (no database)."""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from pydantic import ValidationError

from app.core.ratelimit import RateLimiter
from app.core.security import (
    ACCESS_AUDIENCE,
    PAIRING_ALPHABET,
    PAIRING_CODE_LENGTH,
    UNUSABLE_PASSWORD,
    TokenClaims,
    TokenService,
    format_pairing_code,
    hash_password,
    is_device_token,
    keyed_digest,
    new_device_token,
    new_pairing_code,
    normalize_pairing_code,
    verify_password,
)

from .conftest import build_settings


@pytest.fixture
def tokens(tmp_path: Path) -> TokenService:
    return TokenService(build_settings(tmp_path, "piko_unit"))


CLAIMS = TokenClaims(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())


# ---- passwords ----
def test_password_roundtrip_and_wrong_password() -> None:
    h = hash_password("a long enough password", 4)
    assert verify_password("a long enough password", h)
    assert not verify_password("another password!!", h)


def test_password_over_72_bytes_rejected_not_truncated() -> None:
    with pytest.raises(ValueError):
        hash_password("x" * 73, 4)
    h = hash_password("x" * 72, 4)
    assert not verify_password("x" * 73, h)


def test_unusable_and_malformed_hashes_fail_closed() -> None:
    assert not verify_password("anything", UNUSABLE_PASSWORD)
    assert not verify_password("anything", "not-a-bcrypt-hash")
    assert not verify_password("", hash_password("abc", 4))


# ---- JWTs ----
def test_access_token_roundtrip(tokens: TokenService) -> None:
    assert tokens.verify(tokens.issue_access(CLAIMS), "access") == CLAIMS


def test_expired_token_rejected(tokens: TokenService) -> None:
    old = datetime.now(UTC) - timedelta(seconds=tokens.access_ttl + 5)
    assert tokens.verify(tokens.issue_access(CLAIMS, now=old), "access") is None


def test_refresh_token_cannot_be_used_as_access_and_vice_versa(tokens: TokenService) -> None:
    assert tokens.verify(tokens.issue_refresh(CLAIMS), "access") is None
    assert tokens.verify(tokens.issue_access(CLAIMS), "refresh") is None


def test_wrong_audience_rejected(tokens: TokenService, tmp_path: Path) -> None:
    other = TokenService(build_settings(tmp_path, "piko_unit"))  # same key file, same service
    payload = {
        "iss": "piko", "aud": "someone-else", "sub": str(CLAIMS.user_id),
        "sid": str(CLAIMS.session_id), "typ": "access",
        "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1),
    }  # fmt: skip
    forged = jwt.encode(payload, other._private_key, algorithm="RS256")  # type: ignore[arg-type]
    assert tokens.verify(forged, "access") is None


def test_wrong_issuer_rejected(tokens: TokenService) -> None:
    payload = {
        "iss": "evil", "aud": ACCESS_AUDIENCE, "sub": str(CLAIMS.user_id),
        "sid": str(CLAIMS.session_id), "typ": "access",
        "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1),
    }  # fmt: skip
    assert (
        tokens.verify(jwt.encode(payload, tokens._private_key, algorithm="RS256"), "access") is None
    )  # type: ignore[arg-type]


def test_token_signed_by_another_key_rejected(
    tokens: TokenService, tmp_path_factory: pytest.TempPathFactory
) -> None:
    attacker = TokenService(build_settings(tmp_path_factory.mktemp("attacker"), "piko_unit"))
    assert tokens.verify(attacker.issue_access(CLAIMS), "access") is None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_alg_none_and_hs256_confusion_rejected(tokens: TokenService) -> None:
    payload = {
        "iss": "piko", "aud": ACCESS_AUDIENCE, "sub": str(CLAIMS.user_id),
        "sid": str(CLAIMS.session_id), "typ": "access",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }  # fmt: skip
    assert tokens.verify(jwt.encode(payload, None, algorithm="none"), "access") is None
    # Classic key confusion: HS256 token MACed with the (public) RSA key. PyJWT refuses to build
    # one, so craft it by hand and prove the verifier rejects it.
    public_pem = tokens._public_key.public_bytes(  # type: ignore[attr-defined]
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signing_input = (
        _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        + "."
        + _b64(json.dumps(payload).encode())
    )
    mac = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    assert tokens.verify(signing_input + "." + _b64(mac), "access") is None


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "pkd_x", "Bearer x"])
def test_garbage_tokens_rejected(tokens: TokenService, garbage: str) -> None:
    assert tokens.verify(garbage, "access") is None


# ---- device tokens and pairing codes ----
def test_device_tokens_are_prefixed_unique_and_high_entropy() -> None:
    a, b = new_device_token(), new_device_token()
    assert a != b and is_device_token(a) and len(a) >= 40


def test_pairing_code_shape_and_normalization() -> None:
    code = new_pairing_code()
    assert len(code) == PAIRING_CODE_LENGTH and set(code) <= set(PAIRING_ALPHABET)
    shown = format_pairing_code(code)
    assert shown.count("-") == 2
    assert normalize_pairing_code(shown) == code
    assert normalize_pairing_code(shown.lower().replace("-", " ")) == code


@pytest.mark.parametrize(
    "bad", ["", "ABC", "ABC-DEF-GH1", "ABC-DEF-GHIJ", "ILO-ILO-ILO", "'; DROP--"]
)
def test_malformed_pairing_codes_rejected(bad: str) -> None:
    assert normalize_pairing_code(bad) is None


def test_keyed_digest_is_keyed_and_domain_separated() -> None:
    assert keyed_digest(b"k" * 32, "a", "v") != keyed_digest(b"j" * 32, "a", "v")
    assert keyed_digest(b"k" * 32, "a", "v") != keyed_digest(b"k" * 32, "b", "v")


# ---- settings guards ----
def test_weak_bcrypt_rounds_rejected_outside_tests(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        build_settings(tmp_path, "piko_unit", env="development", bcrypt_rounds=4)


@pytest.mark.parametrize(
    "schema", ["public", "auth", "storage", "pg_catalog", "Bad-Name", "a;drop", ""]
)
def test_reserved_or_unsafe_schema_names_rejected(tmp_path: Path, schema: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(tmp_path, schema)


def test_production_requires_https(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        build_settings(tmp_path, "piko_unit", env="production", bcrypt_rounds=12)


# ---- rate limiter ----
def test_rate_limiter_blocks_then_recovers() -> None:
    now = [0.0]
    rl = RateLimiter(clock=lambda: now[0])
    assert all(rl.check("b", "k", 3, 60)[0] for _ in range(3))
    allowed, remaining, retry = rl.check("b", "k", 3, 60)
    assert not allowed and remaining == 0 and retry >= 1
    assert rl.check("b", "other-key", 3, 60)[0]  # keys are independent
    assert rl.check("other-bucket", "k", 3, 60)[0]  # buckets are independent
    now[0] = 61
    assert rl.check("b", "k", 3, 60)[0]

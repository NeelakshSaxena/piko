"""Operator CLI: key generation never overwrites; first-parent bootstrap validates input."""

import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import cli
from app.core.config import Settings

from .conftest import unique_email


def test_generate_keys_creates_files_and_never_overwrites(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "keys"
    assert cli.main(["generate-keys", "--dir", str(target)]) == 0
    pem, hmac_key = (target / "jwt_private.pem").read_bytes(), (target / "hmac.key").read_bytes()
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----") and len(hmac_key) == 32
    assert "BEGIN" not in capsys.readouterr().out, "key material must never be printed"
    # A second run refuses and leaves the existing keys untouched.
    assert cli.main(["generate-keys", "--dir", str(target)]) == 1
    assert (target / "jwt_private.pem").read_bytes() == pem and (
        target / "hmac.key"
    ).read_bytes() == hmac_key
    if os.name == "posix":  # Windows ignores POSIX mode bits; ACLs inherit from the directory
        for name in ("jwt_private.pem", "hmac.key"):
            assert stat.S_IMODE((target / name).stat().st_mode) == 0o600


def test_create_family_makes_a_parent_who_can_log_in(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    answers = iter(["a long operator password", "a long operator password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    email = unique_email("operator")
    assert cli.main(["create-family", "--email", email, "--family-name", "Operators"]) == 0
    resp = client.post(
        "/api/v1/auth/session", json={"email": email, "password": "a long operator password"}
    )
    assert resp.status_code == 200 and resp.json()["families"][0]["name"] == "Operators"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("short", "short"),
        ("x" * 73, "x" * 73),
        ("a long enough password", "a different password!!"),
    ],
)
def test_create_family_rejects_weak_overlong_or_mismatched_passwords(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    answers = iter([first, second])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    assert cli.main(["create-family", "--email", unique_email("weak"), "--family-name", "X"]) == 1


def test_bootstrap_rejects_invalid_and_duplicate_emails(db: Session, settings: Settings) -> None:
    from app.services.bootstrap import create_family_with_parent

    with pytest.raises(ValueError, match="invalid email"):
        create_family_with_parent(
            db, settings, email="not-an-email", password="x" * 20, family_name="F"
        )
    email = unique_email("dupe")
    create_family_with_parent(db, settings, email=email, password="x" * 20, family_name="F")
    with pytest.raises(ValueError, match="already exists"):
        create_family_with_parent(
            db, settings, email=email.upper(), password="y" * 20, family_name="G"
        )

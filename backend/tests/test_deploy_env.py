"""Secret environment variables -> private key files (serverless deployment adapter)."""

import base64
import os
import stat
import sys
from pathlib import Path

import pytest

from app.deploy_env import SECRET_FILES, SecretDecodeError, materialize_secret_files


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_each_secret_becomes_a_private_file_and_its_file_variable_is_set(tmp_path: Path) -> None:
    env = {
        "PIKO_HMAC_KEY_B64": b64(b"h" * 32),
        "PIKO_FCM_SERVICE_ACCOUNT_B64": b64(b'{"client_email":"x"}'),
    }
    set_vars = materialize_secret_files(env, tmp_path / "s")
    assert set(set_vars) == {"PIKO_HMAC_KEY_FILE", "PIKO_FCM_SERVICE_ACCOUNT_FILE"}
    assert Path(env["PIKO_HMAC_KEY_FILE"]).read_bytes() == b"h" * 32
    assert Path(env["PIKO_FCM_SERVICE_ACCOUNT_FILE"]).read_bytes() == b'{"client_email":"x"}'
    if sys.platform != "win32":
        for var in set_vars:
            assert stat.S_IMODE(os.stat(env[var]).st_mode) == 0o600  # owner only


def test_an_operator_supplied_file_variable_is_never_overridden(tmp_path: Path) -> None:
    env = {"PIKO_HMAC_KEY_B64": b64(b"h" * 32), "PIKO_HMAC_KEY_FILE": "/mnt/real/hmac.key"}
    assert materialize_secret_files(env, tmp_path) == []
    assert env["PIKO_HMAC_KEY_FILE"] == "/mnt/real/hmac.key"


def test_nothing_is_written_when_nothing_is_configured(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    assert materialize_secret_files(env, tmp_path / "s") == []
    assert env == {}
    assert list((tmp_path / "s").iterdir()) == []


@pytest.mark.parametrize("bad", ["not base64!!", "====", "abc"])
def test_invalid_base64_fails_clearly_without_echoing_the_value(tmp_path: Path, bad: str) -> None:
    env = {"PIKO_JWT_PRIVATE_KEY_B64": bad}
    with pytest.raises(SecretDecodeError) as caught:
        materialize_secret_files(env, tmp_path)
    assert "PIKO_JWT_PRIVATE_KEY_B64" in str(caught.value) and bad not in str(caught.value)
    assert "PIKO_JWT_PRIVATE_KEY_FILE" not in env


def test_every_secret_variable_maps_to_a_distinct_file_variable() -> None:
    assert len(set(SECRET_FILES.values())) == len(SECRET_FILES)
    assert all(k.endswith("_B64") and v.endswith("_FILE") for k, v in SECRET_FILES.items())

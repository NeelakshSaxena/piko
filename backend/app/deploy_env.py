"""Turns secret values supplied as environment variables into the secret FILES the application reads.

A serverless host (for example Vercel) has no persistent disk and no place to mount a key file, but it
does have a secret store that exposes values as environment variables. Piko deliberately reads keys from
files so they never appear in an environment dump or a settings object; this adapter bridges the two at
start-up: each `*_B64` variable (base64 of the file's bytes) is written to a private temporary file and the
matching `*_FILE` variable is pointed at it. Values are never logged, printed or placed in an exception.
"""

import base64
import binascii
import os
from collections.abc import MutableMapping
from pathlib import Path

# secret variable -> variable that names the file the application reads
SECRET_FILES = {
    "PIKO_JWT_PRIVATE_KEY_B64": "PIKO_JWT_PRIVATE_KEY_FILE",
    "PIKO_HMAC_KEY_B64": "PIKO_HMAC_KEY_FILE",
    "PIKO_FCM_SERVICE_ACCOUNT_B64": "PIKO_FCM_SERVICE_ACCOUNT_FILE",
    "PIKO_VAPID_PRIVATE_KEY_B64": "PIKO_VAPID_PRIVATE_KEY_FILE",
    "PIKO_OUTBOX_RUN_TOKEN_B64": "PIKO_OUTBOX_RUN_TOKEN_FILE",
}


class SecretDecodeError(ValueError):
    """A *_B64 variable is not valid base64. The message names the variable, never its value."""


def materialize_secret_files(env: MutableMapping[str, str], directory: Path) -> list[str]:
    """Writes each present `*_B64` secret to `directory` (mode 0600) and sets its `*_FILE` variable.

    A `*_FILE` variable that is already set wins (an operator who mounts real files keeps control).
    Returns the names of the `*_FILE` variables it set."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass  # not supported everywhere (Windows); the files below are still created in a fresh private directory
    set_vars: list[str] = []
    for secret_var, file_var in SECRET_FILES.items():
        value = env.get(secret_var)
        if not value or env.get(file_var):
            continue
        try:
            data = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise SecretDecodeError(f"{secret_var} is not valid base64") from None
        path = directory / file_var.lower()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        env[file_var] = str(path)
        set_vars.append(file_var)
    return set_vars

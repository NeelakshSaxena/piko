"""Operator commands: `python -m app.cli generate-keys | create-family`.

There is no public signup endpoint (docs/API_CONTRACTS.md defines none), so the first parent and
family are created here. Passwords are read from a prompt, never from argv or the environment.
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path

from app.core.config import get_settings
from app.core.security import generate_rsa_private_pem, password_is_acceptable_length
from app.db.session import make_engine, make_session_factory
from app.services.bootstrap import create_family_with_parent

MIN_PASSWORD_LENGTH = 12


def generate_keys(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    targets: dict[str, Callable[[], bytes]] = {
        "jwt_private.pem": generate_rsa_private_pem,
        "hmac.key": lambda: os.urandom(32),
    }
    for name in targets:
        if (directory / name).exists():
            print(f"refusing to overwrite existing {directory / name}", file=sys.stderr)
            return 1
    for name, make in targets.items():
        # O_EXCL: never replace an existing key; mode 0600 from creation (no chmod race).
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(make())
    print(f"wrote key files to {directory}")
    print(f"set PIKO_JWT_PRIVATE_KEY_FILE={directory / 'jwt_private.pem'}")
    print(f"set PIKO_HMAC_KEY_FILE={directory / 'hmac.key'}")
    return 0


def create_family(email: str, family_name: str) -> int:
    password = getpass.getpass("Password (min 12 chars): ")
    if len(password) < MIN_PASSWORD_LENGTH or not password_is_acceptable_length(password):
        print("password must be 12 characters and at most 72 bytes", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("passwords differ", file=sys.stderr)
        return 1
    settings = get_settings()
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        user_id, family_id = create_family_with_parent(
            db, settings, email=email, password=password, family_name=family_name
        )
    print(f"created user {user_id} and family {family_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    keys = sub.add_parser("generate-keys", help="create JWT signing key and HMAC key files")
    keys.add_argument("--dir", type=Path, default=Path(".data/keys"))
    fam = sub.add_parser("create-family", help="create the first parent account and family")
    fam.add_argument("--email", required=True)
    fam.add_argument("--family-name", required=True)
    args = parser.parse_args(argv)
    if args.command == "generate-keys":
        return generate_keys(args.dir)
    return create_family(args.email, args.family_name)


if __name__ == "__main__":
    raise SystemExit(main())

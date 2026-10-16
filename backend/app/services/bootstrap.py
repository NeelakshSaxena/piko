"""Operator bootstrap: first parent + family (no public signup endpoint exists)."""

import uuid

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.db.models import Family, FamilyMembership, User


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError("invalid email address") from exc


def create_family_with_parent(
    db: Session, settings: Settings, *, email: str, password: str, family_name: str
) -> tuple[uuid.UUID, uuid.UUID]:
    email = normalize_email(email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ValueError("an account with this email already exists")
    user = User(email=email, password_hash=hash_password(password, settings.bcrypt_rounds))
    family = Family(name=family_name)
    db.add_all([user, family])
    db.flush()
    db.add(FamilyMembership(family_id=family.id, user_id=user.id, role="parent"))
    db.commit()
    return user.id, family.id

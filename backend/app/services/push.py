"""Registration of push delivery addresses (ADR-023).

An FCM token is registered by the paired device itself (authenticated by its device credential) and
always belongs to that device's family, never to a family named in the request. A browser
subscription is registered by an authenticated parent, admin or guardian for their own family.
Registrations die with the device (revocation) and are re-checked against membership at send time.
"""

import json
import uuid
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import keyed_digest
from app.db.models import DevicePushToken, WebPushSubscription
from app.services import audit
from app.services.authz import view_family_id
from app.services.principals import DevicePrincipal, UserPrincipal
from app.services.push_secrets import PushSecretBox

MAX_WEB_SUBSCRIPTIONS_PER_USER = 5
# Only the push services of the major browsers. The server POSTs to this address, so an
# unrestricted value would be a server-side request forgery primitive.
WEB_PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    ".push.services.mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
)
MAX_ENDPOINT_LENGTH = 2048


def validate_web_push_endpoint(endpoint: str, extra_hosts: tuple[str, ...] = ()) -> str:
    """Returns the endpoint if it is an https URL on an allowed push service, else raises 400."""
    bad = ApiError("VALIDATION_ERROR", "That push endpoint is not accepted.")
    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise bad
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        raise bad from None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        raise bad
    allowed = tuple(WEB_PUSH_HOST_SUFFIXES) + extra_hosts
    if not any(host == s.lstrip(".") or (s.startswith(".") and host.endswith(s)) for s in allowed):
        raise bad
    return endpoint


class PushRegistry:
    def __init__(self, settings: Settings, hmac_key: bytes) -> None:
        self._hmac_key = hmac_key
        self._box = PushSecretBox(hmac_key)
        self._extra_hosts: tuple[str, ...] = ()
        del settings

    # ---- Android (FCM) ----
    def register_device_token(self, db: Session, device: DevicePrincipal, token: str) -> None:
        digest = keyed_digest(self._hmac_key, "fcm-token", token)
        # A token identifies one app install. If it is presented by this (authenticated) device it
        # now belongs here, so any older registration of the same token on another device is dropped.
        db.execute(
            delete(DevicePushToken).where(
                DevicePushToken.token_hash == digest, DevicePushToken.device_id != device.device_id
            )
        )
        cipher = self._box.seal(token, "fcm-token")
        stmt = pg_insert(DevicePushToken).values(
            device_id=device.device_id,
            family_id=device.family_id,
            platform="fcm",
            token_hash=digest,
            token_cipher=cipher,
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["device_id"],
                set_={
                    "token_hash": digest,
                    "token_cipher": cipher,
                    "family_id": device.family_id,
                    "updated_at": func.now(),
                },
            )
        )
        audit.record(
            db, action="push_registered", resource_type="device", family_id=device.family_id,
            actor_device_id=device.device_id, resource_id=device.device_id,
        )  # fmt: skip
        db.commit()

    def remove_device_token(self, db: Session, device: DevicePrincipal) -> None:
        removed = cast(
            CursorResult[Any],
            db.execute(
                delete(DevicePushToken).where(DevicePushToken.device_id == device.device_id)
            ),
        ).rowcount
        if removed:
            audit.record(
                db, action="push_revoked", resource_type="device", family_id=device.family_id,
                actor_device_id=device.device_id, resource_id=device.device_id,
            )  # fmt: skip
        db.commit()

    def open_device_token(self, row: DevicePushToken) -> str | None:
        return self._box.open(row.token_cipher, "fcm-token")

    # ---- Browser (Web Push) ----
    def register_web_subscription(
        self, db: Session, user: UserPrincipal, endpoint: str, p256dh: str, auth: str
    ) -> None:
        validate_web_push_endpoint(endpoint, self._extra_hosts)
        family_id = view_family_id(db, user.user_id)  # parent, admin or guardian only
        digest = keyed_digest(self._hmac_key, "webpush-endpoint", endpoint)
        sealed = self._box.seal(
            json.dumps({"endpoint": endpoint, "p256dh": p256dh, "auth": auth}), "webpush"
        )
        stmt = pg_insert(WebPushSubscription).values(
            id=uuid.uuid4(), user_id=user.user_id, family_id=family_id,
            endpoint_hash=digest, secret_cipher=sealed,
        )  # fmt: skip
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["endpoint_hash"],
                # The same browser signing in as someone else becomes that person's subscription.
                set_={
                    "user_id": user.user_id,
                    "family_id": family_id,
                    "secret_cipher": sealed,
                    "updated_at": func.now(),
                },
            )
        )
        # Keep the newest few per user so a script cannot grow the table or the fan-out.
        ids = list(
            db.scalars(
                select(WebPushSubscription.id)
                .where(WebPushSubscription.user_id == user.user_id)
                .order_by(WebPushSubscription.updated_at.desc())
            )
        )
        if len(ids) > MAX_WEB_SUBSCRIPTIONS_PER_USER:
            db.execute(
                delete(WebPushSubscription).where(
                    WebPushSubscription.id.in_(ids[MAX_WEB_SUBSCRIPTIONS_PER_USER:])
                )
            )
        audit.record(
            db, action="push_registered", resource_type="user", family_id=family_id,
            actor_user_id=user.user_id, resource_id=user.user_id,
        )  # fmt: skip
        db.commit()

    def remove_web_subscription(self, db: Session, user: UserPrincipal, endpoint: str) -> None:
        digest = keyed_digest(self._hmac_key, "webpush-endpoint", endpoint)
        removed = cast(
            CursorResult[Any],
            db.execute(
                delete(WebPushSubscription).where(
                    WebPushSubscription.endpoint_hash == digest,
                    WebPushSubscription.user_id == user.user_id,  # nobody removes another person's
                )
            ),
        ).rowcount
        if removed:
            audit.record(
                db, action="push_revoked", resource_type="user", actor_user_id=user.user_id,
                resource_id=user.user_id,
            )  # fmt: skip
        db.commit()

    def open_web_subscription(self, row: WebPushSubscription) -> dict[str, str] | None:
        raw = self._box.open(row.secret_cipher, "webpush")
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
            return None
        return value

    def allow_extra_web_push_hosts(self, hosts: tuple[str, ...]) -> None:
        """For tests and private push services only; never set from request data."""
        self._extra_hosts = hosts

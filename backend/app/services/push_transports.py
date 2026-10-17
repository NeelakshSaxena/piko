"""The two real push transports: FCM HTTP v1 (Android) and W3C Web Push with VAPID (browsers).

Both map provider answers to the four outcomes of `notifications.SendResult` and never put an
address, token, key or response body into an exception message or a log line.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import jwt

from app.services.notifications import (
    Accepted,
    InvalidTarget,
    Permanent,
    SendResult,
    Transient,
)

log = logging.getLogger("piko.push")

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
_FCM_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"


class FcmTransport:
    """Sends a high-priority, data-only message. The phone wakes, fetches the authoritative state from
    the API and shows its own privacy-safe notification; the message itself carries no content."""

    def __init__(
        self,
        project_id: str,
        service_account: dict[str, Any],
        client: httpx.Client | None = None,
    ) -> None:
        self._project = project_id
        self._email = str(service_account["client_email"])
        self._key = str(service_account["private_key"])
        self._token_uri = str(service_account.get("token_uri") or _DEFAULT_TOKEN_URI)
        self._http = client or httpx.Client(timeout=10.0)
        self._access: tuple[str, float] | None = None

    @classmethod
    def from_file(cls, project_id: str, path: Path) -> "FcmTransport":
        return cls(project_id, json.loads(path.read_text(encoding="utf-8")))

    def _access_token(self) -> str | None:
        now = time.time()
        if self._access and self._access[1] - 60 > now:
            return self._access[0]
        assertion = jwt.encode(
            {
                "iss": self._email,
                "scope": FCM_SCOPE,
                "aud": self._token_uri,
                "iat": int(now),
                "exp": int(now) + 3300,
            },
            self._key,
            algorithm="RS256",
        )
        resp = self._http.post(
            self._token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        self._access = (str(body["access_token"]), now + float(body.get("expires_in", 3600)))
        return self._access[0]

    def send(self, address: str, payload: dict[str, str], ttl_seconds: int) -> SendResult:
        try:
            token = self._access_token()
            if token is None:
                return Transient("fcm_auth_failed")
            resp = self._http.post(
                _FCM_URL.format(project=self._project),
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "message": {
                        "token": address,
                        "data": payload,  # strings only, ids and a type, no content
                        "android": {"priority": "HIGH", "ttl": f"{ttl_seconds}s"},
                    }
                },
            )
        except (httpx.HTTPError, ValueError, KeyError):
            return Transient("fcm_network")
        if resp.status_code == 200:
            return Accepted()
        if resp.status_code in (401, 403):
            self._access = None  # force a new token next time; credentials may need attention
            return Transient("fcm_auth")
        if resp.status_code == 404 or _fcm_error_code(resp) == "UNREGISTERED":
            return InvalidTarget("fcm_unregistered")
        if resp.status_code == 429 or resp.status_code >= 500:
            return Transient(f"fcm_http_{resp.status_code}")
        return Permanent(f"fcm_http_{resp.status_code}")


def _fcm_error_code(resp: httpx.Response) -> str | None:
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            code = detail.get("errorCode")
            if code:
                return str(code)
    except (ValueError, AttributeError):
        return None
    return None


class WebPushTransport:
    def __init__(self, private_key_file: Path, subject: str) -> None:
        self._key_file = str(private_key_file)
        self._subject = subject

    def send(self, address: str, payload: dict[str, str], ttl_seconds: int) -> SendResult:
        from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]  # lazy: optional

        try:
            subscription = json.loads(address)
            webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
                },
                data=json.dumps(payload),
                vapid_private_key=self._key_file,
                vapid_claims={"sub": self._subject},
                ttl=min(ttl_seconds, 86400),
                timeout=10,
            )
            return Accepted()
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                return InvalidTarget("webpush_gone")
            if status is None:
                # No HTTP answer and a WebPushException: pywebpush rejected the subscription itself
                # (bad key or auth secret). Network failures are OSError subclasses, handled below.
                return Permanent("webpush_bad_subscription")
            if status == 429 or status >= 500:
                return Transient(f"webpush_http_{status}")
            return Permanent(f"webpush_http_{status}")
        except (ValueError, KeyError):
            return Permanent("webpush_bad_subscription")
        except OSError:
            return Transient("webpush_network")

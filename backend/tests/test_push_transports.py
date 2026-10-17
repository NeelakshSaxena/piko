"""The real push transports, with the network leg replaced.

- Web Push: pywebpush really encrypts (RFC 8291) and signs (VAPID); a local HTTP server plays the browser's
  push service, and the test decrypts the message with the subscription's private key. This proves the
  payload that leaves the server is content-free and well-formed. It does NOT contact Google, Mozilla or
  Apple.
- FCM v1: httpx's MockTransport plays oauth2.googleapis.com and fcm.googleapis.com, so the OAuth assertion,
  the request body and the error mapping are checked, but no message goes to Firebase.
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.services.notifications import Accepted, InvalidTarget, Permanent, Transient
from app.services.push_transports import FcmTransport, WebPushTransport


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


# ---- Web Push ----------------------------------------------------------------------------------------------
class _Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, str], bytes]] = []
        self.status = 201
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", 0))
                outer.requests.append(
                    ({k.lower(): v for k, v in self.headers.items()}, self.rfile.read(length))
                )
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/push/abc"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def push_service():  # type: ignore[no-untyped-def]
    rec = _Recorder()
    yield rec
    rec.close()


@pytest.fixture
def vapid(tmp_path: Path) -> Path:
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "vapid.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def browser_subscription(endpoint: str):  # type: ignore[no-untyped-def]
    """What a browser would hand the server: an endpoint, a P-256 public key and a 16-byte auth secret."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = b"0123456789abcdef"
    return private, auth, {"endpoint": endpoint, "p256dh": b64u(public), "auth": b64u(auth)}


def decrypt(body: bytes, private, auth: bytes) -> bytes:  # type: ignore[no-untyped-def]
    import http_ece

    return http_ece.decrypt(body, private_key=private, auth_secret=auth)


def test_a_web_push_is_encrypted_signed_and_carries_only_a_type_and_an_id(
    push_service, vapid
) -> None:  # type: ignore[no-untyped-def]
    private, auth, sub = browser_subscription(push_service.url)
    result = WebPushTransport(vapid, "mailto:ops@example.com").send(
        json.dumps(sub),
        {"v": "1", "type": "sos_created", "id": "3f1b7c3e-9d5a-4b1c-8a2e-0c9d4e5f6a7b"},
        600,
    )
    assert isinstance(result, Accepted)
    ((headers, body),) = push_service.requests
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["authorization"].lower().startswith("vapid ")
    assert headers["ttl"] == "600"
    assert b"sos_created" not in body  # the wire body is ciphertext
    plain = json.loads(decrypt(body, private, auth))
    assert plain == {"v": "1", "type": "sos_created", "id": "3f1b7c3e-9d5a-4b1c-8a2e-0c9d4e5f6a7b"}


def test_web_push_maps_provider_answers_to_outcomes(push_service, vapid) -> None:  # type: ignore[no-untyped-def]
    _, _, sub = browser_subscription(push_service.url)
    transport = WebPushTransport(vapid, "mailto:ops@example.com")
    payload = {"v": "1", "type": "message", "id": "x"}
    expected = {
        404: InvalidTarget,
        410: InvalidTarget,
        429: Transient,
        500: Transient,
        503: Transient,
        400: Permanent,
        401: Permanent,
        403: Permanent,
        413: Permanent,
    }
    for status, kind in expected.items():
        push_service.status = status
        assert isinstance(transport.send(json.dumps(sub), payload, 60), kind), status
    push_service.status = 201
    assert isinstance(transport.send(json.dumps(sub), payload, 60), Accepted)


def test_web_push_failures_before_the_network_are_not_retried_blindly(vapid) -> None:  # type: ignore[no-untyped-def]
    transport = WebPushTransport(vapid, "mailto:ops@example.com")
    payload = {"v": "1", "type": "message", "id": "x"}
    assert isinstance(
        transport.send("not json", payload, 60), Permanent
    )  # a corrupt stored subscription
    assert isinstance(
        transport.send(
            json.dumps({"endpoint": "http://127.0.0.1:1/x", "p256dh": "AA", "auth": "AA"}),
            payload,
            60,
        ),
        Permanent,
    )
    dead = "http://127.0.0.1:9/unreachable"
    _, _, sub = browser_subscription(dead)
    assert isinstance(
        transport.send(json.dumps(sub), payload, 60), Transient
    )  # nobody listening: try later


# ---- FCM HTTP v1 -------------------------------------------------------------------------------------------------
@pytest.fixture
def service_account():  # type: ignore[no-untyped-def]
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key()
    return {
        "client_email": "piko-test@example-project.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }, public


class FakeGoogle:
    def __init__(
        self,
        public_key,
        fcm_status: int = 200,
        fcm_body: dict | None = None,
        token_status: int = 200,
    ) -> None:  # type: ignore[no-untyped-def]
        self.public = public_key
        self.fcm_status, self.fcm_body, self.token_status = fcm_status, fcm_body or {}, token_status
        self.token_requests = 0
        self.fcm_requests: list[dict] = []  # type: ignore[type-arg]
        self.auth_headers: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            self.token_requests += 1
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            assert form["grant_type"].startswith("urn%3Aietf")
            claims = jwt.decode(
                form["assertion"],
                self.public,
                algorithms=["RS256"],
                audience="https://oauth2.googleapis.com/token",
            )
            assert claims["iss"] == "piko-test@example-project.iam.gserviceaccount.com"
            assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
            return httpx.Response(
                self.token_status, json={"access_token": "ya29.test", "expires_in": 3600}
            )
        assert request.url.host == "fcm.googleapis.com"
        assert request.url.path == "/v1/projects/demo-project/messages:send"
        self.auth_headers.append(request.headers["authorization"])
        self.fcm_requests.append(json.loads(request.content))
        return httpx.Response(self.fcm_status, json=self.fcm_body)


def make(service_account, **kwargs):  # type: ignore[no-untyped-def]
    account, public = service_account
    google = FakeGoogle(public, **kwargs)
    return FcmTransport(
        "demo-project", account, client=httpx.Client(transport=httpx.MockTransport(google))
    ), google


def test_an_fcm_message_is_data_only_high_priority_and_content_free(service_account) -> None:  # type: ignore[no-untyped-def]
    transport, google = make(service_account)
    result = transport.send("device-token-123", {"v": "1", "type": "message", "id": "abc"}, 7200)
    assert isinstance(result, Accepted)
    (sent,) = google.fcm_requests
    message = sent["message"]
    assert message["token"] == "device-token-123"
    assert message["data"] == {"v": "1", "type": "message", "id": "abc"}
    assert "notification" not in message  # the app builds its own privacy-safe notification
    assert message["android"] == {"priority": "HIGH", "ttl": "7200s"}
    assert google.auth_headers == ["Bearer ya29.test"]


def test_the_oauth_token_is_cached_until_it_expires(service_account) -> None:  # type: ignore[no-untyped-def]
    transport, google = make(service_account)
    for _ in range(3):
        transport.send("t", {"v": "1", "type": "message", "id": "a"}, 60)
    assert google.token_requests == 1 and len(google.fcm_requests) == 3


@pytest.mark.parametrize(
    ("status", "body", "kind", "code"),
    [
        (404, {"error": {"status": "NOT_FOUND"}}, InvalidTarget, "fcm_unregistered"),
        (
            400,
            {"error": {"status": "INVALID_ARGUMENT", "details": [{"errorCode": "UNREGISTERED"}]}},
            InvalidTarget,
            "fcm_unregistered",
        ),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, Permanent, "fcm_http_400"),
        (429, {}, Transient, "fcm_http_429"),
        (500, {}, Transient, "fcm_http_500"),
        (503, {}, Transient, "fcm_http_503"),
        (401, {}, Transient, "fcm_auth"),
        (403, {}, Transient, "fcm_auth"),
    ],
)
def test_fcm_answers_map_to_outcomes(service_account, status, body, kind, code) -> None:  # type: ignore[no-untyped-def]
    transport, _ = make(service_account, fcm_status=status, fcm_body=body)
    result = transport.send("t", {"v": "1", "type": "message", "id": "a"}, 60)
    assert isinstance(result, kind) and result.code == code  # type: ignore[union-attr]


def test_a_failed_oauth_exchange_is_a_retryable_failure_not_a_crash(service_account) -> None:  # type: ignore[no-untyped-def]
    transport, google = make(service_account, token_status=401)
    result = transport.send("t", {"v": "1", "type": "message", "id": "a"}, 60)
    assert (
        isinstance(result, Transient)
        and result.code == "fcm_auth_failed"
        and google.fcm_requests == []
    )


def test_a_network_error_is_retryable(service_account) -> None:  # type: ignore[no-untyped-def]
    account, _ = service_account

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    transport = FcmTransport(
        "demo-project", account, client=httpx.Client(transport=httpx.MockTransport(boom))
    )
    assert isinstance(transport.send("t", {"v": "1", "type": "message", "id": "a"}, 60), Transient)


def test_the_service_account_key_never_appears_in_an_outcome(service_account) -> None:  # type: ignore[no-untyped-def]
    account, _ = service_account
    transport, _ = make(
        service_account, fcm_status=500, fcm_body={"error": {"message": account["private_key"]}}
    )
    result = transport.send("tok-secret", {"v": "1", "type": "message", "id": "a"}, 60)
    assert "PRIVATE KEY" not in repr(result) and "tok-secret" not in repr(result)

"""Registers a SYNTHETIC browser subscription for the e2e parent (TEST TOOLING).

The endpoint is on an allow-listed push host but is not a real browser: a real push service will answer a
send to it with an error (404/410/400/401), which is exactly what lets the test see the server's real Web
Push transport, VAPID signing and error mapping work against a real provider. Nothing private is sent.
"""

import base64
import json
import sys
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[2]
state = json.loads((ROOT / ".data" / "e2e" / "state.json").read_text())
BASE = "http://127.0.0.1:8000/api/v1"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return r.status, json.loads(raw) if raw else None


b64u = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
_, session = call("POST", "/auth/session", {"email": state["email"], "password": state["password"]})
token = session["access_token"]
public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
endpoint = sys.argv[1] if len(sys.argv) > 1 else "https://fcm.googleapis.com/fcm/send/piko-synthetic-subscription-for-testing"
status, _ = call("PUT", "/push/web-subscription", {"endpoint": endpoint, "keys": {"p256dh": b64u(public), "auth": b64u(b"0123456789abcdef")}}, token)
print("registered synthetic subscription:", status)

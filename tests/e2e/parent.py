"""Parent-side helper against the e2e server (TEST TOOLING).  usage: parent.py <cmd> [args]

code | incidents | ack <id> | resolve <id> | msg <text> | messages | health | run | devices | revoke-newest
Acts as the synthetic parent in .data/e2e/state.json and always targets the NEWEST paired device.
"""

import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = json.loads((ROOT / ".data" / "e2e" / "state.json").read_text())
RUN_TOKEN = (ROOT / ".data" / "e2e" / "keys" / "outbox_run_token").read_text().strip()
BASE = "http://127.0.0.1:8000/api/v1"


def call(method, path, body=None, token=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None


def login():
    s, b = call("POST", "/auth/session", {"email": STATE["email"], "password": STATE["password"]})
    assert s == 200, (s, b)
    return b["access_token"]


def newest_device(token):
    s, fam = call("GET", "/families", token=token)
    fid = fam["families"][0]["id"]
    s, detail = call("GET", f"/families/{fid}", token=token)
    devices = [d for d in detail["devices"] if d["status"] != "revoked"]
    return sorted(devices, key=lambda d: d["paired_at"])[-1]["id"] if devices else None


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    token = login()
    if cmd == "code":
        s, b = call("POST", "/devices/pairing-code", token=token)
        print(b["pairing_code"] if s == 201 else (s, b))
    elif cmd == "devices":
        s, fam = call("GET", "/families", token=token)
        s, d = call("GET", f"/families/{fam['families'][0]['id']}", token=token)
        for x in d["devices"]:
            print(x["id"], x["status"], x["paired_at"])
    elif cmd == "incidents":
        s, b = call("GET", "/sos/incidents", token=token)
        for i in b["incidents"]:
            print(i["incident_id"], i["status"], "raised", i["triggered_at"], "msg=", i["message"])
        print("total", b["total_count"])
    elif cmd in ("ack", "resolve"):
        s, b = call("PUT", f"/sos/incidents/{args[0]}", {"status": "acknowledged" if cmd == "ack" else "resolved"}, token)
        print(s, b["status"] if s == 200 else b)
    elif cmd == "msg":
        device = newest_device(token)
        s, b = call("POST", "/messages", {"message_id": str(uuid.uuid4()), "body": args[0], "sent_at": datetime.now(UTC).isoformat(), "device_id": device}, token)
        print(s, b["status"] if s < 300 else b)
    elif cmd == "messages":
        s, b = call("GET", f"/messages?device_id={newest_device(token)}", token=token)
        for m in b["messages"]:
            print(m["sender"], m["status"], repr(m["body"]))
        print("total", b["total_count"])
    elif cmd == "health":
        s, b = call("GET", "/internal/outbox/health", headers={"X-Piko-Outbox-Token": RUN_TOKEN})
        print(s, json.dumps(b))
    elif cmd == "run":
        s, b = call("POST", "/internal/outbox/run", headers={"X-Piko-Outbox-Token": RUN_TOKEN})
        print(s, json.dumps(b))
    elif cmd == "revoke-newest":
        device = newest_device(token)
        s, _ = call("DELETE", f"/devices/{device}", token=token)
        print(s)


main()

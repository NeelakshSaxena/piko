"""Local end-to-end server for the emulator and a browser. TEST TOOLING: not part of the product.

- Creates (once) a throwaway `piko_test_e2e_*` schema, migrates it to head and makes a synthetic parent.
- Serves the real API on 127.0.0.1:8000 (reachable from the emulator as 10.0.2.2).
- Browser push is REAL Web Push (VAPID keys generated into .data/e2e/, never committed).
- Android push is SIMULATED: the outbox's device transport sends an `adb shell am broadcast` to the debug-only
  SimulatePushReceiver instead of calling Firebase. This exercises the outbox, retries, authorization and the
  phone's handling of a push; it does NOT prove Google's delivery leg. A real FCM run needs a Firebase
  project (docs/PUSH_NOTIFICATIONS.md).

Run:  .venv\\Scripts\\python tests\\e2e\\run_e2e_server.py      (stop with Ctrl-C / by killing the process)
State (schema name, synthetic credentials) is written to .data/e2e/state.json.
"""

import contextlib
import io
import json
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
STATE_DIR = ROOT / ".data" / "e2e"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE = STATE_DIR / "state.json"
ADB = ROOT / ".tools" / "android" / "platform-tools" / "adb.exe"

import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.cli import generate_push_secrets  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.session import make_engine, make_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.bootstrap import create_family_with_parent  # noqa: E402
from app.services.notifications import Accepted, InvalidTarget, SendResult, Transient  # noqa: E402


class AdbBroadcastTransport:
    """Delivers the push to the one emulator by broadcast. The address (token) is not used."""

    def send(self, address: str, payload: dict[str, str], ttl_seconds: int) -> SendResult:
        # Fault knobs for the scenarios (files, so they can change while the server runs):
        if (STATE_DIR / "adb_down").exists():
            return Transient("adb_unavailable")  # "the push service is down"
        if (STATE_DIR / "fcm_unregistered").exists():
            return InvalidTarget("fcm_unregistered")  # "the token has been revoked by Google"
        cmd = [
            str(ADB), "shell", "am", "broadcast", "-a", "app.piko.android.debug.SIMULATE_PUSH",
            "-n", "app.piko.android/.debug.SimulatePushReceiver",
            "--es", "v", payload["v"], "--es", "type", payload["type"], "--es", "id", payload["id"],
        ]  # fmt: skip
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return Transient("adb_unavailable")
        return Accepted() if "Broadcast completed" in out.stdout else Transient("adb_failed")


def main() -> None:
    state = json.loads(STATE.read_text()) if STATE.exists() else None
    keys = STATE_DIR / "keys"
    if state is None:
        if not (keys / "vapid_private.pem").exists():
            with contextlib.redirect_stdout(io.StringIO()):
                generate_push_secrets(keys)
        from cryptography.hazmat.primitives import serialization
        import base64

        private = serialization.load_pem_private_key((keys / "vapid_private.pem").read_bytes(), None)
        public = private.public_key().public_bytes(  # type: ignore[union-attr]
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        state = {
            "schema": "piko_test_e2e_" + secrets.token_hex(3),
            "email": f"e2e-{secrets.token_hex(3)}@example.com",
            "password": secrets.token_urlsafe(18),
            "vapid_public": base64.urlsafe_b64encode(public).decode().rstrip("="),
        }
    settings = Settings(
        _env_file=ROOT / ".env",
        db_schema=state["schema"],
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "10.0.2.2"],
        allowed_origins=["http://127.0.0.1:4173", "http://127.0.0.1:5173"],
        vapid_private_key_file=keys / "vapid_private.pem",
        vapid_public_key=state["vapid_public"],
        vapid_subject="mailto:e2e@example.com",
        outbox_run_token_file=keys / "outbox_run_token",
    )  # type: ignore[call-arg]
    if not STATE.exists():
        cfg = Config(str(ROOT / "backend" / "alembic.ini"))
        cfg.attributes["settings"] = settings
        command.upgrade(cfg, "head")
        with make_session_factory(make_engine(settings))() as db:
            create_family_with_parent(
                db, settings, email=state["email"], password=state["password"], family_name="E2E (safe to delete)"
            )
        STATE.write_text(json.dumps(state))
        print("schema ready:", state["schema"], flush=True)
    app = create_app(settings)
    app.state.notifier.transports["device_token"] = AdbBroadcastTransport()
    uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False, log_level="warning")


if __name__ == "__main__":
    main()

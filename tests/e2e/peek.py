"""Read-only counts for the e2e schema (TEST TOOLING). Prints numbers and statuses only: no tokens, no text."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import Settings  # noqa: E402

state = json.loads((ROOT / ".data" / "e2e" / "state.json").read_text())
schema = state["schema"]
assert schema.startswith("piko_test_e2e_")
s = Settings(_env_file=ROOT / ".env")  # type: ignore[call-arg]
engine = create_engine(make_url(s.database_url.get_secret_value()), connect_args={"options": "-c default_transaction_read_only=on"})
with engine.connect() as c:
    q = lambda sql: c.execute(text(sql.replace("S.", f'"{schema}".'))).all()  # noqa: E731
    print("device_push_tokens:", q("SELECT count(*) FROM S.device_push_tokens")[0][0], "hash:", *[r[0][:8] for r in q("SELECT token_hash FROM S.device_push_tokens")])
    print("web_push_subscriptions:", q("SELECT count(*) FROM S.web_push_subscriptions")[0][0])
    for row in q("SELECT kind, target_kind, status, attempts, coalesce(last_error,'-') FROM S.notification_outbox ORDER BY created_at"):
        print("outbox:", *row)
engine.dispose()

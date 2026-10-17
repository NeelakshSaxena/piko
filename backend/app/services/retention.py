"""Retention (ADR-011, ADR-023): delete data that has outlived its documented purpose.

- telemetry events older than the family's `retention_days` (history is kept per family, 30 days by default);
- messages older than `message_retention_days` (90);
- audit events older than `audit_retention_days` (365);
- finished notification-outbox rows older than `outbox_retention_days` (30);
- refresh sessions that expired or were revoked more than a week ago, and old used/expired pairing and
  invitation codes.

SOS incidents are NEVER deleted here: they are safety records (docs/DATA_MODEL.md). Deletion happens in
bounded batches so a large backlog cannot hold a lock or exhaust a free-tier database's time limit, and a
dry run (the default) reports what would go without touching anything.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

BATCH = 2000


@dataclass
class RetentionReport:
    dry_run: bool
    counts: dict[str, int] = field(default_factory=dict)
    more_remaining: bool = False


class RetentionService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _rules(self, now: datetime) -> list[tuple[str, str, str, dict[str, object]]]:
        """(name, table, WHERE over alias `t`, params). The statements below never take user input."""
        s = self._s
        return [
            (
                "telemetry_events",
                "telemetry_events",
                "t.occurred_at < :now - (SELECT f.retention_days FROM families f WHERE f.id = t.family_id) * interval '1 day'",
                {"now": now},
            ),
            (
                "messages",
                "messages",
                "t.received_at < :cut",
                {"cut": now - timedelta(days=s.message_retention_days)},
            ),
            (
                "audit_events",
                "audit_events",
                "t.created_at < :cut",
                {"cut": now - timedelta(days=s.audit_retention_days)},
            ),
            (
                "notification_outbox",
                "notification_outbox",
                "t.status <> 'pending' AND t.created_at < :cut",
                {"cut": now - timedelta(days=s.outbox_retention_days)},
            ),
            (
                "refresh_sessions",
                "refresh_sessions",
                "(t.expires_at < :cut OR t.revoked_at < :cut)",
                {"cut": now - timedelta(days=7)},
            ),
            (
                "pairing_invitations",
                "pairing_invitations",
                "t.status <> 'pending' AND t.created_at < :cut OR t.expires_at < :cut",
                {"cut": now - timedelta(days=1)},
            ),
            (
                "member_invitations",
                "member_invitations",
                "t.expires_at < :cut",
                {"cut": now - timedelta(days=30)},
            ),
        ]

    def run(
        self,
        factory: sessionmaker[Session],
        *,
        apply: bool = False,
        max_batches: int = 50,
        now: datetime | None = None,
    ) -> RetentionReport:
        when = now or datetime.now(UTC)
        report = RetentionReport(dry_run=not apply)
        for name, table, where, params in self._rules(when):
            if not apply:
                with factory() as db:
                    count = db.execute(
                        text(f"SELECT count(*) FROM {table} t WHERE {where}"), params
                    ).scalar()
                report.counts[name] = int(count or 0)
                continue
            total = 0
            for _ in range(max_batches):
                with factory() as db:
                    deleted = cast(
                        CursorResult[Any],
                        db.execute(
                            text(
                                f"DELETE FROM {table} WHERE ctid IN "
                                f"(SELECT t.ctid FROM {table} t WHERE {where} LIMIT {BATCH})"
                            ),
                            params,
                        ),
                    ).rowcount
                    db.commit()
                total += deleted
                if deleted < BATCH:
                    break
            else:
                report.more_remaining = True  # the batch budget ran out: run again to continue
            report.counts[name] = total
        return report

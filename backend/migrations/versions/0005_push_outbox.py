"""Push registrations and the notification outbox (ADR-023)

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_ACTIONS_OLD = (
    "'login', 'logout', 'device_paired', 'device_revoked', 'member_invited', 'member_revoked', "
    "'location_accessed', 'sos_created', 'sos_resolved', 'credential_rotated', 'session_revoked', "
    "'settings_changed', 'member_joined', 'sos_acknowledged'"
)
_ACTIONS_NEW = _ACTIONS_OLD + ", 'push_registered', 'push_revoked', 'message_read'"


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expression)


def _ts(name: str, nullable: bool = True) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "device_push_tokens",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=8), server_default="fcm", nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_cipher", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("platform IN ('fcm')"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.PrimaryKeyConstraint("device_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "web_push_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("secret_cipher", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_hash"),
    )
    op.create_index("ix_webpush_user", "web_push_subscriptions", ["user_id"])
    op.create_index("ix_webpush_family", "web_push_subscriptions", ["family_id"])
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        _ts("next_attempt_at", nullable=False),
        _ts("expires_at", nullable=False),
        sa.Column("last_error", sa.String(length=48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        _ts("accepted_at"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'dead', 'skipped', 'expired')"),
        sa.CheckConstraint("target_kind IN ('device_token', 'web_subscription')"),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        "ix_outbox_due",
        "notification_outbox",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    _replace_check("audit_events", "audit_events_action_check", f"action IN ({_ACTIONS_NEW})")


def downgrade() -> None:
    # Registrations and queued notifications are runtime state; the downgrade drops them.
    op.execute(
        "DELETE FROM audit_events WHERE action IN ('push_registered', 'push_revoked', 'message_read')"
    )
    _replace_check("audit_events", "audit_events_action_check", f"action IN ({_ACTIONS_OLD})")
    op.drop_index("ix_outbox_due", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("ix_webpush_family", table_name="web_push_subscriptions")
    op.drop_index("ix_webpush_user", table_name="web_push_subscriptions")
    op.drop_table("web_push_subscriptions")
    op.drop_table("device_push_tokens")

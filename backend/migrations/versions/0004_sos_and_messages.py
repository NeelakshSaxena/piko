"""SOS incidents and family messages (ADR-022)

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_ACTIONS_OLD = (
    "'login', 'logout', 'device_paired', 'device_revoked', 'member_invited', 'member_revoked', "
    "'location_accessed', 'sos_created', 'sos_resolved', 'credential_rotated', 'session_revoked', "
    "'settings_changed', 'member_joined'"
)
_ACTIONS_NEW = _ACTIONS_OLD + ", 'sos_acknowledged'"


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expression)


def _ts(name: str, nullable: bool = True) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "sos_incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("message", sa.String(length=280), nullable=True),
        _ts("triggered_at", nullable=False),
        _ts("received_at", nullable=False),
        sa.Column("location_latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("location_longitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("location_accuracy_meters", sa.Numeric(8, 2), nullable=True),
        _ts("location_captured_at"),
        sa.Column("location_is_latest_known", sa.Boolean(), server_default="false", nullable=False),
        _ts("acknowledged_at"),
        sa.Column("acknowledged_by_member_id", sa.Uuid(), nullable=True),
        _ts("resolved_at"),
        sa.Column("resolved_by_member_id", sa.Uuid(), nullable=True),
        sa.Column("parent_notes", sa.String(length=500), nullable=True),
        sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved')"),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by_member_id"], ["family_memberships.id"]),
        sa.ForeignKeyConstraint(["resolved_by_member_id"], ["family_memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sos_family_received", "sos_incidents", ["family_id", sa.text("received_at DESC")]
    )
    op.create_index("ix_sos_device", "sos_incidents", ["device_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column("sender_member_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="delivered", nullable=False),
        _ts("sent_at", nullable=False),
        _ts("received_at", nullable=False),
        _ts("acknowledged_at"),
        sa.Column("acknowledged_by_member_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("sender IN ('device', 'parent')"),
        sa.CheckConstraint("status IN ('delivered', 'acknowledged')"),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["sender_member_id"], ["family_memberships.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by_member_id"], ["family_memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_device_received", "messages", ["device_id", sa.text("received_at DESC")]
    )
    _replace_check("audit_events", "audit_events_action_check", f"action IN ({_ACTIONS_NEW})")


def downgrade() -> None:
    # SOS incidents and messages are safety records: this downgrade drops them. Back up first.
    op.execute("DELETE FROM audit_events WHERE action = 'sos_acknowledged'")
    _replace_check("audit_events", "audit_events_action_check", f"action IN ({_ACTIONS_OLD})")
    op.drop_index("ix_messages_device_received", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_sos_device", table_name="sos_incidents")
    op.drop_index("ix_sos_family_received", table_name="sos_incidents")
    op.drop_table("sos_incidents")

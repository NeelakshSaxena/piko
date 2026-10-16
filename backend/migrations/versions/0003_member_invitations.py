"""Member invitations and the limited `guardian` role (ADR-017)

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_ACTIONS_OLD = (
    "'login', 'logout', 'device_paired', 'device_revoked', 'member_invited', 'member_revoked', "
    "'location_accessed', 'sos_created', 'sos_resolved', 'credential_rotated', 'session_revoked', "
    "'settings_changed'"
)
_ACTIONS_NEW = _ACTIONS_OLD + ", 'member_joined'"


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expression)


def upgrade() -> None:
    op.create_table(
        "member_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("invitee_email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_member_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'used', 'expired', 'revoked')"),
        sa.CheckConstraint("role IN ('parent', 'family_admin', 'guardian')"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["used_by_member_id"], ["family_memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        "ix_invitations_family_email_pending",
        "member_invitations",
        ["family_id", "invitee_email"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    _replace_check(
        "family_memberships",
        "family_memberships_role_check",
        "role IN ('parent', 'family_admin', 'guardian', 'child')",
    )
    _replace_check("audit_events", "audit_events_action_check", f"action IN ({_ACTIONS_NEW})")


def downgrade() -> None:
    # The old constraints cannot hold guardian memberships or 'member_joined' audit rows, so a
    # downgrade necessarily removes them (the invitations table is dropped first: it references
    # memberships). Back up before downgrading.
    op.drop_index("ix_invitations_family_email_pending", table_name="member_invitations")
    op.drop_table("member_invitations")
    op.execute("DELETE FROM family_memberships WHERE role = 'guardian'")
    op.execute("DELETE FROM audit_events WHERE action = 'member_joined'")
    _replace_check(
        "family_memberships",
        "family_memberships_role_check",
        "role IN ('parent', 'family_admin', 'child')",
    )
    _replace_check("audit_events", "audit_events_action_check", f"action IN ({_ACTIONS_OLD})")

"""Audit actions for the read-only MCP adapter (ADR-024)

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_ACTIONS_OLD = (
    "'login', 'logout', 'device_paired', 'device_revoked', 'member_invited', 'member_revoked', "
    "'location_accessed', 'sos_created', 'sos_resolved', 'credential_rotated', 'session_revoked', "
    "'settings_changed', 'member_joined', 'sos_acknowledged', "
    "'push_registered', 'push_revoked', 'message_read'"
)
_ACTIONS_NEW = _ACTIONS_OLD + ", 'mcp_token_issued', 'mcp_token_revoked', 'mcp_tool_called'"


def _replace_check(expression: str) -> None:
    op.drop_constraint("audit_events_action_check", "audit_events", type_="check")
    op.create_check_constraint("audit_events_action_check", "audit_events", expression)


def upgrade() -> None:
    _replace_check(f"action IN ({_ACTIONS_NEW})")


def downgrade() -> None:
    op.execute(
        "DELETE FROM audit_events WHERE action IN "
        "('mcp_token_issued', 'mcp_token_revoked', 'mcp_tool_called')"
    )
    _replace_check(f"action IN ({_ACTIONS_OLD})")

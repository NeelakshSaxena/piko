"""Phase 3 telemetry: append-only events and derived latest state

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_latest_state",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("location_latitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("location_longitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("location_accuracy_meters", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("location_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("battery_percent", sa.Integer(), nullable=True),
        sa.Column("battery_is_charging", sa.Boolean(), nullable=True),
        sa.Column("battery_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connectivity_network_type", sa.String(length=32), nullable=True),
        sa.Column("connectivity_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
        ),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "telemetry_events",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("event_type IN ('location', 'battery', 'connectivity')"),
        sa.CheckConstraint("sequence_number IS NULL OR sequence_number >= 0"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
        ),
        sa.PrimaryKeyConstraint("device_id", "id"),
    )
    op.create_index(
        "ix_events_device_occurred",
        "telemetry_events",
        ["device_id", sa.literal_column("occurred_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_device_occurred", table_name="telemetry_events")
    op.drop_table("telemetry_events")
    op.drop_table("device_latest_state")

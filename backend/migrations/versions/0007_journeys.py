"""Journeys: local-first trips synced from the owning device (ADR-026)

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_MODES = "'FLIGHT', 'TRAIN', 'TAXI', 'BIKE_TAXI', 'METRO', 'BUS', 'WALKING', 'OTHER'"
_EVENTS = (
    "'tracking_started', 'tracking_paused', 'tracking_resumed', 'tracking_stopped', "
    "'arrival_detected', 'arrival_confirmed', 'observation', 'network_restored', 'journey_completed'"
)


def _ts(name: str, nullable: bool = True) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "journeys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        _ts("received_at", nullable=False),
        _ts("deleted_at"),
        sa.CheckConstraint("status IN ('DRAFT', 'PLANNED')"),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journeys_device_updated", "journeys", ["device_id", sa.text("updated_at DESC")]
    )
    op.create_table(
        "journey_legs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("service_number", sa.String(length=80), nullable=True),
        sa.Column("origin", sa.String(length=80), nullable=False),
        sa.Column("destination", sa.String(length=80), nullable=False),
        _ts("departure_at"),
        sa.Column("departure_zone", sa.String(length=64), nullable=True),
        _ts("arrival_at"),
        sa.Column("arrival_zone", sa.String(length=64), nullable=True),
        sa.CheckConstraint(f"mode IN ({_MODES})"),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("journey_id", "sequence"),
    )
    op.create_table(
        "journey_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journey_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        _ts("occurred_at", nullable=False),
        _ts("received_at", nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(f"event_type IN ({_EVENTS})"),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journey_events_journey", "journey_events", ["journey_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("journey_events")
    op.drop_table("journey_legs")
    op.drop_table("journeys")

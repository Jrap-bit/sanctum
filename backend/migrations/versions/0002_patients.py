"""Patient profiles, scoped access, timeline and follow-up tasks."""
from alembic import op
import sqlalchemy as sa

revision = "0002_patients"
down_revision = "0001_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("patients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("primary_practitioner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="patient_status"))
    op.create_index("ix_patients_status", "patients", ["status"])
    op.create_table("patient_access",
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True))
    op.create_table("patient_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False))
    op.create_index("ix_patient_events_patient_id", "patient_events", ["patient_id"])
    op.create_table("follow_ups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('open', 'completed', 'cancelled')", name="follow_up_state"))
    op.create_index("ix_follow_ups_patient_id", "follow_ups", ["patient_id"])


def downgrade():
    op.drop_table("follow_ups")
    op.drop_table("patient_events")
    op.drop_table("patient_access")
    op.drop_table("patients")

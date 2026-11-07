"""Encrypted AI drafts and durable summary generation jobs."""
from alembic import op
import sqlalchemy as sa
revision = "0008_ai_summaries"
down_revision = "0007_document_review"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("ai_summaries",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("patient_id",sa.String(36),sa.ForeignKey("patients.id"),nullable=False),
        sa.Column("created_by",sa.String(36),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("kind",sa.String(24),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False),
        sa.Column("payload",sa.LargeBinary(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_ai_summaries_patient_id","ai_summaries",["patient_id"])
    op.create_table("summary_jobs",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("patient_id",sa.String(36),sa.ForeignKey("patients.id"),nullable=False),
        sa.Column("requested_by",sa.String(36),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("request_key",sa.String(36),nullable=False),
        sa.Column("request_hash",sa.String(64),nullable=False),
        sa.Column("kind",sa.String(24),nullable=False),
        sa.Column("payload",sa.LargeBinary(),nullable=False),
        sa.Column("state",sa.String(16),nullable=False),
        sa.Column("attempts",sa.Integer(),nullable=False),
        sa.Column("run_id",sa.String(36),nullable=True),
        sa.Column("lease_until",sa.DateTime(timezone=True),nullable=True),
        sa.Column("message",sa.String(240),nullable=True),
        sa.Column("summary_id",sa.String(36),sa.ForeignKey("ai_summaries.id"),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("requested_by","request_key",name="summary_request_key"),
        sa.CheckConstraint("state IN ('queued','running','completed','failed','cancelled')",name="summary_job_state"))
    op.create_index("ix_summary_jobs_patient_id","summary_jobs",["patient_id"])
    op.create_index("ix_summary_jobs_state","summary_jobs",["state"])

def downgrade():
    op.drop_table("summary_jobs")
    op.drop_table("ai_summaries")

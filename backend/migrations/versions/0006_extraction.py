"""Durable document extraction queue and encrypted draft pages."""
from alembic import op
import sqlalchemy as sa
revision = "0006_extraction"
down_revision = "0005_documents"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("extraction_jobs",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("document_id",sa.String(36),sa.ForeignKey("stored_documents.id"),nullable=False,unique=True),
        sa.Column("requested_by",sa.String(36),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("state",sa.String(16),nullable=False),
        sa.Column("completed_pages",sa.Integer(),nullable=False),
        sa.Column("attempts",sa.Integer(),nullable=False),
        sa.Column("run_id",sa.String(36),nullable=True),
        sa.Column("lease_until",sa.DateTime(timezone=True),nullable=True),
        sa.Column("message",sa.String(240),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",name="extraction_state"))
    op.create_index("ix_extraction_jobs_state","extraction_jobs",["state"])
    op.create_table("extracted_pages",
        sa.Column("document_id",sa.String(36),sa.ForeignKey("stored_documents.id"),primary_key=True),
        sa.Column("page_number",sa.Integer(),primary_key=True),
        sa.Column("payload",sa.LargeBinary(),nullable=False))

def downgrade():
    op.drop_table("extracted_pages")
    op.drop_table("extraction_jobs")

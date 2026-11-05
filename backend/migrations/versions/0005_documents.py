"""Encrypted patient document originals."""
from alembic import op
import sqlalchemy as sa
revision = "0005_documents"
down_revision = "0004_account_credentials"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("stored_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("metadata_payload", sa.LargeBinary(), nullable=False),
        sa.Column("original_payload", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("patient_id", "digest", name="document_patient_digest"))
    op.create_index("ix_stored_documents_patient_id", "stored_documents", ["patient_id"])

def downgrade():
    op.drop_table("stored_documents")

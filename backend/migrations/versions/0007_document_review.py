"""Versioned page reviews and one confirmed import per document."""
from alembic import op
import sqlalchemy as sa
revision = "0007_document_review"
down_revision = "0006_extraction"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("stored_documents", sa.Column("review_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("extracted_pages", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table("document_imports",
        sa.Column("document_id",sa.String(36),sa.ForeignKey("stored_documents.id"),primary_key=True),
        sa.Column("payload",sa.LargeBinary(),nullable=False))

def downgrade():
    op.drop_table("document_imports")
    op.drop_column("extracted_pages","version")
    op.drop_column("stored_documents","review_version")

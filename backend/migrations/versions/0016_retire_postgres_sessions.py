"""Sessions and login limits now live in Redis; originals live in the object store."""
from alembic import op
import sqlalchemy as sa

revision = '0016_retire_postgres_sessions'
down_revision = '0015_platform_contracts'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('login_sessions')
    op.drop_table('login_buckets')
    op.drop_column('stored_documents', 'original_payload')


def downgrade():
    op.add_column('stored_documents', sa.Column('original_payload', sa.LargeBinary(), nullable=True))
    op.create_table('login_buckets',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True))
    op.create_table('login_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True))

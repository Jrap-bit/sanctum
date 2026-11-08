"""Object-store references, OAuth identity, model selection, reports, deletion registry, backups."""
from alembic import op
import sqlalchemy as sa

revision = '0015_platform_contracts'
down_revision = '0014_access_requests'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('email', sa.String(254), nullable=True))
    op.add_column('users', sa.Column('google_sub', sa.String(255), nullable=True))
    op.create_unique_constraint('uq_users_email', 'users', ['email'])
    op.create_unique_constraint('uq_users_google_sub', 'users', ['google_sub'])
    op.drop_constraint('patient_status', 'patients', type_='check')
    op.create_check_constraint('patient_status', 'patients', "status IN ('active', 'archived', 'deleting')")
    op.add_column('stored_documents', sa.Column('object_key', sa.String(255), nullable=True))
    op.add_column('stored_documents', sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('stored_documents', 'original_payload', existing_type=sa.LargeBinary(), nullable=True)
    op.add_column('summary_jobs', sa.Column('model', sa.String(80), nullable=True))
    op.create_table('reports',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('patient_id', sa.String(36), sa.ForeignKey('patients.id'), nullable=False, index=True),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('payload', sa.LargeBinary(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('content_digest', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('exported_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('previewed', 'exported')", name='report_state'))
    op.create_table('deletion_registry',
        sa.Column('opaque_id', sa.String(64), primary_key=True),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reason', sa.LargeBinary(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('deleting', 'completed')", name='deletion_state'))
    op.create_table('backups',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('verified', sa.Boolean(), nullable=False),
        sa.Column('manifest', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('backups')
    op.drop_table('deletion_registry')
    op.drop_table('reports')
    op.drop_column('summary_jobs', 'model')
    op.drop_column('stored_documents', 'withdrawn_at')
    op.drop_column('stored_documents', 'object_key')
    op.drop_constraint('uq_users_google_sub', 'users', type_='unique')
    op.drop_constraint('uq_users_email', 'users', type_='unique')
    op.drop_column('users', 'google_sub')
    op.drop_column('users', 'email')
    op.drop_constraint('patient_status', 'patients', type_='check')
    op.create_check_constraint('patient_status', 'patients', "status IN ('active', 'archived')")

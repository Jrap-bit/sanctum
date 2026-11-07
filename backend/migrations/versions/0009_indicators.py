"""Retained encrypted indicator input/result snapshots and separate reviews."""
from alembic import op
import sqlalchemy as sa
revision='0009_indicators'
down_revision='0008_ai_summaries'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('indicator_runs',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('patient_id',sa.String(36),sa.ForeignKey('patients.id'),nullable=False),
        sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('input_digest',sa.String(64),nullable=False),
        sa.Column('payload',sa.LargeBinary(),nullable=False),
        sa.Column('reviews',sa.LargeBinary(),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_indicator_runs_patient_id','indicator_runs',['patient_id'])

def downgrade():
    op.drop_table('indicator_runs')

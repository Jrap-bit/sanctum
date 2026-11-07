"""Confirmed source-linked concern inputs."""
from alembic import op
import sqlalchemy as sa
revision='0011_concerns'
down_revision='0010_ratings'
branch_labels=None
depends_on=None

def upgrade():
 op.create_table('confirmed_concerns',
  sa.Column('id',sa.String(36),primary_key=True),
  sa.Column('patient_id',sa.String(36),sa.ForeignKey('patients.id'),nullable=False),
  sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
  sa.Column('payload',sa.LargeBinary(),nullable=False),
  sa.Column('withdrawal',sa.LargeBinary(),nullable=True),
  sa.Column('state',sa.String(16),nullable=False),
  sa.Column('version',sa.Integer(),nullable=False),
  sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
  sa.CheckConstraint("state IN ('confirmed','withdrawn')",name='concern_state'))
 op.create_index('ix_confirmed_concerns_patient_id','confirmed_concerns',['patient_id'])

def downgrade():op.drop_table('confirmed_concerns')

"""Patient-scoped approval records; no automatic patient access."""
from alembic import op
import sqlalchemy as sa
revision='0014_access_requests'
down_revision='0013_rule_versions'
branch_labels=None
depends_on=None

def upgrade():
 op.create_table('clinical_grants',sa.Column('id',sa.String(36),primary_key=True),
  sa.Column('patient_id',sa.String(36),sa.ForeignKey('patients.id'),nullable=False),
  sa.Column('subject_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
  sa.Column('requester_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
  sa.Column('approver_id',sa.String(36),sa.ForeignKey('users.id'),nullable=True),
  sa.Column('capability',sa.String(32),nullable=False),sa.Column('state',sa.String(16),nullable=False),
  sa.Column('version',sa.Integer(),nullable=False),sa.Column('payload',sa.LargeBinary(),nullable=False),
  sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('reviewed_at',sa.DateTime(timezone=True),nullable=True),
  sa.CheckConstraint("state IN ('pending','approved','denied','revoked','cancelled')",name='clinical_grant_state'),
  sa.CheckConstraint("capability IN ('clinical:read','clinical:write')",name='clinical_grant_capability'))
 op.create_index('ix_clinical_grants_patient_id','clinical_grants',['patient_id']);op.create_index('ix_clinical_grants_subject_id','clinical_grants',['subject_id'])

def downgrade():op.drop_table('clinical_grants')

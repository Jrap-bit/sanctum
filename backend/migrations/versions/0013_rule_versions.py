"""Immutable rule revisions and current-version pointers."""
from alembic import op
import sqlalchemy as sa
revision='0013_rule_versions'
down_revision='0012_medications'
branch_labels=None
depends_on=None

def upgrade():
 op.create_table('rule_heads',sa.Column('id',sa.String(40),primary_key=True),sa.Column('current_version',sa.Integer(),nullable=False))
 revisions=op.create_table('rule_revisions',sa.Column('rule_id',sa.String(40),sa.ForeignKey('rule_heads.id'),primary_key=True),sa.Column('version',sa.Integer(),primary_key=True),sa.Column('parameters',sa.JSON(),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('reason',sa.String(1000),nullable=False),sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
 heads=sa.table('rule_heads',sa.column('id',sa.String),sa.column('current_version',sa.Integer))
 defaults={'repeated-concern':{'W':3,'K':3},'difficulty-scale':{'D':2},'overdue-followup':{},'medication-change':{'L':30},'missing-documentation':{}}
 op.bulk_insert(heads,[{'id':key,'current_version':1} for key in defaults])
 op.bulk_insert(revisions,[{'rule_id':key,'version':1,'parameters':params,'enabled':True,'reason':'Built-in defaults'} for key,params in defaults.items()])
 if op.get_bind().dialect.name=='postgresql':
  op.execute("CREATE FUNCTION prevent_rule_revision_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Published rule revisions are immutable'; END; $$")
  op.execute('CREATE TRIGGER immutable_rule_revision BEFORE UPDATE OR DELETE ON rule_revisions FOR EACH ROW EXECUTE FUNCTION prevent_rule_revision_change()')

def downgrade():
 if op.get_bind().dialect.name=='postgresql':
  op.execute('DROP TRIGGER immutable_rule_revision ON rule_revisions');op.execute('DROP FUNCTION prevent_rule_revision_change()')
 op.drop_table('rule_revisions');op.drop_table('rule_heads')

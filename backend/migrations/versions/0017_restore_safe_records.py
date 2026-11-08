"""Deletion markers and backup records survive a restore that replaces the users table."""
from alembic import op

revision = '0017_restore_safe_records'
down_revision = '0016_retire_postgres_sessions'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('deletion_registry_actor_id_fkey', 'deletion_registry', type_='foreignkey')
    op.drop_constraint('backups_created_by_fkey', 'backups', type_='foreignkey')


def downgrade():
    op.create_foreign_key('backups_created_by_fkey', 'backups', 'users', ['created_by'], ['id'])
    op.create_foreign_key('deletion_registry_actor_id_fkey', 'deletion_registry', 'users', ['actor_id'], ['id'])

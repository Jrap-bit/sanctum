"""Initial user accounts, revocable sessions, login limits and audit events."""
from alembic import op
import sqlalchemy as sa

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_table("login_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_login_buckets_expires_at", "login_buckets", ["expires_at"])
    op.create_table("audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("audit_events")
    op.drop_table("login_buckets")
    op.drop_table("login_sessions")
    op.drop_table("users")

"""One-use credential links and account credential state."""
from alembic import op
import sqlalchemy as sa

revision = "0004_account_credentials"
down_revision = "0003_sessions"
branch_labels = None
depends_on = None


def upgrade():
    # Existing accounts already have valid chosen passwords; preserve their access.
    op.add_column("users", sa.Column("credentials_ready", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("password_reset_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("credential_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("issued_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('activation', 'reset')", name="credential_token_purpose"))
    op.create_index("ix_credential_tokens_expires_at", "credential_tokens", ["expires_at"])


def downgrade():
    op.drop_table("credential_tokens")
    op.drop_column("users", "password_reset_required")
    op.drop_column("users", "credentials_ready")

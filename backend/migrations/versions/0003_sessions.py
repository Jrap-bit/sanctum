"""Clinical drafts and immutable finalized notes with linked amendments."""
from alembic import op
import sqlalchemy as sa

revision = "0003_sessions"
down_revision = "0002_patients"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("clinical_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("clinical_notes.id"), nullable=True, unique=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('draft', 'finalized')", name="clinical_note_state"),
        sa.CheckConstraint("version >= 1", name="clinical_note_version"),
        sa.CheckConstraint("(state = 'draft' AND finalized_at IS NULL) OR (state = 'finalized' AND finalized_at IS NOT NULL)", name="clinical_note_finalized_at"))
    op.create_index("ix_clinical_notes_patient_id", "clinical_notes", ["patient_id"])
    if op.get_bind().dialect.name == "postgresql":
        # A second layer of protection: even a direct UPDATE cannot rewrite a final note.
        op.execute("""
            CREATE FUNCTION protect_finalized_note() RETURNS trigger AS $$
            BEGIN
                IF OLD.state = 'finalized' THEN
                    RAISE EXCEPTION 'Finalized notes cannot be updated';
                END IF;
                IF NEW.patient_id IS DISTINCT FROM OLD.patient_id
                   OR NEW.author_id IS DISTINCT FROM OLD.author_id
                   OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
                   OR NEW.id IS DISTINCT FROM OLD.id THEN
                    RAISE EXCEPTION 'Session identity and authorship cannot change';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        op.execute("CREATE TRIGGER clinical_note_immutable BEFORE UPDATE ON clinical_notes FOR EACH ROW EXECUTE FUNCTION protect_finalized_note()")


def downgrade():
    op.drop_table("clinical_notes")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION protect_finalized_note()")

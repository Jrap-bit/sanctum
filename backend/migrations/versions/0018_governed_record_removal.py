"""Let an authorised deletion or restore replace protected rows, in that transaction only."""
from alembic import op

revision = '0018_governed_record_removal'
down_revision = '0017_restore_safe_records'
branch_labels = None
depends_on = None

BYPASS = "current_setting('sanctum.governed_removal', true) = 'on'"


def upgrade():
    op.execute(f"""
        CREATE OR REPLACE FUNCTION protect_finalized_note() RETURNS trigger AS $$
        BEGIN
            IF {BYPASS} THEN
                RETURN NEW;
            END IF;
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
    op.execute(f"""
        CREATE OR REPLACE FUNCTION prevent_rule_revision_change() RETURNS trigger AS $$
        BEGIN
            IF {BYPASS} THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Published rule revisions are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION protect_finalized_note() RETURNS trigger AS $$
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
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_rule_revision_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Published rule revisions are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)

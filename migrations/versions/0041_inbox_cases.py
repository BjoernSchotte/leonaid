"""Inbox-owned entry snapshots, case state, contact correlation and references."""

from alembic import op

revision = "0041_inbox_cases"
down_revision = "0040_material_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inbox_case (
            id uuid PRIMARY KEY,
            public_reference uuid NOT NULL UNIQUE,
            action_id uuid REFERENCES charity_action(id),
            subject text NOT NULL CHECK (char_length(btrim(subject)) BETWEEN 1 AND 240),
            message text NOT NULL CHECK (char_length(btrim(message)) BETWEEN 1 AND 10000),
            given_name text NOT NULL CHECK (char_length(btrim(given_name)) BETWEEN 1 AND 200),
            family_name text NOT NULL CHECK (char_length(btrim(family_name)) BETWEEN 1 AND 200),
            email text CHECK (email IS NULL OR char_length(btrim(email)) BETWEEN 3 AND 320),
            phone text CHECK (phone IS NULL OR char_length(btrim(phone)) BETWEEN 7 AND 40),
            received_at timestamptz NOT NULL DEFAULT now(),
            status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','in_progress','closed')),
            assignee_user_id uuid REFERENCES user_account(id),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            closure_note text CHECK (closure_note IS NULL OR char_length(btrim(closure_note)) BETWEEN 1 AND 4000),
            closed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            contact_create_id uuid NOT NULL UNIQUE,
            contact_job_id uuid NOT NULL UNIQUE REFERENCES outbox_event(id),
            contact_status text NOT NULL DEFAULT 'pending' CHECK (contact_status IN ('pending','linked','needs_review','failed')),
            contact_revision bigint NOT NULL DEFAULT 1 CHECK (contact_revision > 0),
            contact_started_at timestamptz,
            contact_error_code text CHECK (contact_error_code ~ '^[a-z][a-z0-9_]{0,99}$'),
            twenty_person_id uuid,
            contact_linked_at timestamptz,
            CHECK (email IS NOT NULL OR phone IS NOT NULL),
            CHECK ((status='closed') = (closed_at IS NOT NULL)),
            CHECK ((status='closed') = (closure_note IS NOT NULL)),
            CHECK ((contact_status='linked') = (twenty_person_id IS NOT NULL)),
            CHECK ((contact_status='linked') = (contact_linked_at IS NOT NULL)),
            CHECK ((contact_status IN ('failed','needs_review')) = (contact_error_code IS NOT NULL))
        );
        CREATE INDEX ix_inbox_case_action ON inbox_case(action_id, received_at DESC, id);
        CREATE INDEX ix_inbox_case_assignee ON inbox_case(assignee_user_id, status, received_at DESC, id);
        CREATE INDEX ix_inbox_case_status ON inbox_case(status, received_at DESC, id);

        CREATE TABLE inbox_case_task (
            case_id uuid NOT NULL REFERENCES inbox_case(id) ON DELETE CASCADE,
            task_id uuid NOT NULL REFERENCES task(id),
            PRIMARY KEY (case_id, task_id)
        );
        CREATE TABLE inbox_case_material (
            case_id uuid NOT NULL REFERENCES inbox_case(id) ON DELETE CASCADE,
            material_id uuid NOT NULL,
            material_version bigint NOT NULL,
            PRIMARY KEY (case_id, material_id, material_version),
            FOREIGN KEY (material_id, material_version) REFERENCES material_version(material_id, version)
        );
        CREATE TABLE inbox_case_comment (
            id uuid PRIMARY KEY,
            case_id uuid NOT NULL REFERENCES inbox_case(id) ON DELETE CASCADE,
            author_user_id uuid NOT NULL REFERENCES user_account(id),
            body text NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 4000),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_inbox_case_comment_order ON inbox_case_comment(case_id, created_at, id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE inbox_case_comment;
        DROP TABLE inbox_case_material;
        DROP TABLE inbox_case_task;
        DROP TABLE inbox_case;
    """)

"""Materials module: metadata, stored file versions and explicit members.

Revision ID: 0042_materials
Revises: 0041_tasks

File bytes stay in the existing object storage; every stored version keeps
its bucket, key and storage version id, so a reference to a version always
resolves to the same bytes. Knowledge pages reference versions in the
knowledge migration.
"""

from alembic import op

revision = "0042_materials"
down_revision = "0041_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE material (
            id uuid PRIMARY KEY,
            action_id uuid REFERENCES charity_action(id),
            owner_user_id uuid NOT NULL REFERENCES user_account(id),
            title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 240),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            access_revision bigint NOT NULL DEFAULT 1 CHECK (access_revision > 0),
            current_version bigint NOT NULL DEFAULT 1 CHECK (current_version > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_material_action ON material (action_id);
        CREATE INDEX ix_material_owner ON material (owner_user_id);

        CREATE TABLE material_version (
            material_id uuid NOT NULL REFERENCES material(id),
            version bigint NOT NULL CHECK (version > 0),
            filename text NOT NULL CHECK (char_length(btrim(filename)) BETWEEN 1 AND 240),
            media_type text NOT NULL CHECK (char_length(btrim(media_type)) BETWEEN 1 AND 255),
            size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 26214400),
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            storage_bucket text NOT NULL CHECK (char_length(btrim(storage_bucket)) BETWEEN 1 AND 255),
            object_key text NOT NULL CHECK (char_length(btrim(object_key)) BETWEEN 1 AND 1024),
            storage_version_id text NOT NULL CHECK (
                char_length(btrim(storage_version_id)) BETWEEN 1 AND 1024
                AND storage_version_id <> 'null'
            ),
            created_by uuid NOT NULL REFERENCES user_account(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (material_id, version),
            UNIQUE (storage_bucket, object_key, storage_version_id)
        );
        ALTER TABLE material ADD CONSTRAINT material_current_version
            FOREIGN KEY (id, current_version) REFERENCES material_version(material_id, version)
            DEFERRABLE INITIALLY DEFERRED;

        CREATE TABLE material_member (
            material_id uuid NOT NULL REFERENCES material(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES user_account(id),
            access text NOT NULL CHECK (access IN ('viewer', 'editor')),
            PRIMARY KEY (material_id, user_id)
        );
        CREATE INDEX ix_material_member_user ON material_member (user_id, material_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE material_member;
        ALTER TABLE material DROP CONSTRAINT material_current_version;
        DROP TABLE material_version;
        DROP TABLE material;
    """)

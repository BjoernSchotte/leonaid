"""Material-owned metadata, stored versions and knowledge version references."""

from alembic import op

revision = "0040_material_versions"
down_revision = "0039_knowledge_access_revision"
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

        CREATE TABLE knowledge_page_material (
            page_id uuid NOT NULL,
            revision bigint NOT NULL,
            material_id uuid NOT NULL,
            material_version bigint NOT NULL,
            PRIMARY KEY (page_id, revision, material_id, material_version),
            FOREIGN KEY (page_id, revision) REFERENCES knowledge_page_revision(page_id, revision)
                ON DELETE CASCADE,
            FOREIGN KEY (material_id, material_version) REFERENCES material_version(material_id, version)
        );
        CREATE INDEX ix_knowledge_page_material_target
            ON knowledge_page_material (material_id, material_version);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE knowledge_page_material;
        DROP TABLE material_member;
        ALTER TABLE material DROP CONSTRAINT material_current_version;
        DROP TABLE material_version;
        DROP TABLE material;
    """)

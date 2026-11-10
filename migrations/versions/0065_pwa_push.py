"""Push notifications of the PWA: flag `pwa.push`, subscriptions, preferences.

Revision ID: 0065_pwa_push
Revises: 0063_document_series

specs/mails-documents-donations-push §10, ADR-0017. `push_subscription` holds
one row per device and session: the endpoint of the browser vendor's push
service, the device's two keys and the VAPID key it subscribed with. Nothing
about the browser itself is stored. A subscription ends with its session: the
trigger deletes it the moment the session is revoked (sign-out, a revoked
account, erasure), and the foreign key deletes it with the session row.
`push_preference` holds what a member switched on. `push_dispatch` holds, per
member and kind, when the last push went out and how many events wait for the
next one (at most one push in 15 minutes). The feature ships off. The
downgrade drops the three tables, the trigger and the flag row; the audit
events of flag changes stay (they reference the row id, not a foreign key).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0065_pwa_push"
down_revision: str | None = "0063_document_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "Three new empty tables and a trigger on user_session that only deletes "
    "rows of the new table; the known-key check is replaced by a wider one. "
    "Existing sessions and flag rows are untouched."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

OLD_KEYS = (
    "key IN ('admin.system_status_panel', 'admin.preview_notice', "
    "'pwa.offline_queue', 'delivery.tours')"
)
NEW_KEYS = (
    "key IN ('admin.system_status_panel', 'admin.preview_notice', "
    "'pwa.offline_queue', 'delivery.tours', 'pwa.push')"
)
KINDS = "kind IN ('follow_ups', 'feed', 'tasks', 'delivery')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE push_subscription (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE CASCADE,
            session_id uuid NOT NULL
                REFERENCES user_session (id) ON DELETE CASCADE,
            endpoint text NOT NULL
                CONSTRAINT uq_push_subscription_endpoint UNIQUE
                CONSTRAINT ck_push_subscription_endpoint
                CHECK (char_length(endpoint) BETWEEN 1 AND 2048),
            p256dh bytea NOT NULL
                CONSTRAINT ck_push_subscription_p256dh
                CHECK (octet_length(p256dh) = 65),
            auth bytea NOT NULL
                CONSTRAINT ck_push_subscription_auth
                CHECK (octet_length(auth) = 16),
            -- The public VAPID key the browser subscribed with (base64url).
            -- A subscription made with another key than the installation's
            -- current one can never be reached again.
            vapid_public_key text NOT NULL
                CONSTRAINT ck_push_subscription_vapid_public_key
                CHECK (char_length(vapid_public_key) = 87),
            created_at timestamptz NOT NULL DEFAULT now(),
            last_success_at timestamptz,
            -- Messages in a row that the push service did not take for the
            -- device: how many, since when, on how many different club days
            -- and on which day last. All reset with the next delivery.
            failure_count integer NOT NULL DEFAULT 0
                CONSTRAINT ck_push_subscription_failure_count
                CHECK (failure_count >= 0),
            failing_since timestamptz,
            failure_days integer NOT NULL DEFAULT 0
                CONSTRAINT ck_push_subscription_failure_days
                CHECK (failure_days BETWEEN 0 AND failure_count),
            last_failure_on date,
            CONSTRAINT ck_push_subscription_failing
                CHECK (
                    (failure_count = 0) = (failing_since IS NULL)
                    AND (failure_count = 0) = (last_failure_on IS NULL)
                    AND (failure_count = 0) = (failure_days = 0)
                ),
            -- The job whose message this device got last: the same job run
            -- again does not send to it twice.
            last_event_id uuid
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_push_subscription_user ON push_subscription (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_push_subscription_session
            ON push_subscription (session_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE push_preference (
            user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE CASCADE,
            kind text NOT NULL
                CONSTRAINT ck_push_preference_kind CHECK ({KINDS}),
            enabled boolean NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, kind)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE push_dispatch (
            user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE CASCADE,
            kind text NOT NULL
                CONSTRAINT ck_push_dispatch_kind CHECK ({KINDS}),
            last_sent_at timestamptz,
            pending_count integer NOT NULL DEFAULT 0
                CONSTRAINT ck_push_dispatch_pending_count
                CHECK (pending_count >= 0),
            sending_event_id uuid,
            sending_count integer NOT NULL DEFAULT 0
                CONSTRAINT ck_push_dispatch_sending_count
                CHECK (sending_count >= 0),
            PRIMARY KEY (user_id, kind)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION delete_push_subscriptions_of_revoked_session()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          DELETE FROM push_subscription WHERE session_id = NEW.id;
          RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_user_session_revoked_push
        AFTER UPDATE OF revoked_at ON user_session
        FOR EACH ROW
        WHEN (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL)
        EXECUTE FUNCTION delete_push_subscriptions_of_revoked_session()
        """
    )
    op.drop_constraint("ck_feature_flag_known_key", "feature_flag", type_="check")
    op.create_check_constraint("ck_feature_flag_known_key", "feature_flag", NEW_KEYS)
    op.execute(
        "INSERT INTO feature_flag (id, key, enabled, revision) VALUES "
        "('95000000-0000-4000-8000-000000000005', 'pwa.push', false, 1) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DELETE FROM feature_flag WHERE key = 'pwa.push'")
    op.drop_constraint("ck_feature_flag_known_key", "feature_flag", type_="check")
    op.create_check_constraint("ck_feature_flag_known_key", "feature_flag", OLD_KEYS)
    op.execute("DROP TRIGGER trg_user_session_revoked_push ON user_session")
    op.execute("DROP FUNCTION delete_push_subscriptions_of_revoked_session()")
    op.execute("DROP TABLE push_dispatch")
    op.execute("DROP TABLE push_preference")
    op.execute("DROP TABLE push_subscription")
    # Jobs of the dropped feature would dead-letter without a handler.
    op.execute("DELETE FROM outbox_event WHERE event_type = 'push.notification.v1'")

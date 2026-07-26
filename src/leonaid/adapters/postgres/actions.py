"""PostgreSQL persistence for the neutral CharityAction aggregate."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.actions import CharityActionRepository
from leonaid.application.errors import Conflict
from leonaid.domain.action_templates import (
    ActionConfiguration,
    ActionTemplate,
    ActionTemplateKey,
    ActionTemplateSnapshot,
    ConfiguredOffering,
    ConfiguredOrderForm,
    OfferingStatus,
    OfferingUnit,
    OrderFormConfiguration,
    TemplateOffering,
)
from leonaid.domain.actions import (
    ActionManagementState,
    ActionCapability,
    ActionGoal,
    AdministratorOption,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
    PublicationWindow,
    PublicActionAlias,
)


class AsyncpgCharityActionRepository(CharityActionRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def get(self, action_id: UUID) -> CharityAction | None:
        async with self._pool.acquire() as connection:
            return await self._get(connection, action_id)

    async def create(
        self,
        action: CharityAction,
        *,
        responsible_admin_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        configuration: ActionConfiguration | None = None,
    ) -> CharityAction:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO charity_action (
                            id, carrier_name, name, purpose, status,
                            starts_on, ends_on,
                            publication_starts_at, publication_ends_at,
                            archive_slug,
                            goal_value, actual_value, goal_unit, currency,
                            revision, created_at, updated_at
                        )
                        VALUES (
                            $1, $2, $3, $4, $5,
                            $6, $7,
                            $8, $9,
                            $10,
                            $11, $12, $13, $14,
                            $15, $16, $16
                        )
                        """,
                        action.id,
                        action.carrier_name,
                        action.name,
                        action.purpose,
                        action.status.value,
                        action.starts_on,
                        action.ends_on,
                        (
                            action.publication_window.starts_at
                            if action.publication_window is not None
                            else None
                        ),
                        (
                            action.publication_window.ends_at
                            if action.publication_window is not None
                            else None
                        ),
                        action.archive_slug,
                        action.goal.goal_value,
                        action.goal.actual_value,
                        action.goal.unit,
                        action.goal.currency,
                        action.revision,
                        occurred_at,
                    )
                    await self._insert_capabilities(connection, action)
                    await self._insert_beneficiaries(connection, action, occurred_at)
                    if configuration is not None:
                        await self._insert_configuration(
                            connection,
                            configuration,
                            occurred_at,
                        )
                    await connection.execute(
                        """
                        INSERT INTO action_membership (
                            id, action_id, user_id, role, active_from
                        )
                        VALUES ($1, $2, $3, 'charity_admin', $4)
                        """,
                        uuid4(),
                        action.id,
                        responsible_admin_user_id,
                        occurred_at,
                    )
                    await self._audit(
                        connection,
                        action=action,
                        actor_user_id=responsible_admin_user_id,
                        event_type=(
                            "charity_action.copied"
                            if configuration is not None
                            and configuration.snapshot.copied_from_action_id is not None
                            else "charity_action.created"
                        ),
                        request_id=request_id,
                        payload={
                            "status": action.status.value,
                            "capabilities": self._capability_values(action),
                            "beneficiaryCount": len(action.beneficiaries),
                            "goal": self._goal_payload(action.goal),
                            "template": (
                                self._snapshot_reference(configuration)
                                if configuration is not None
                                else None
                            ),
                        },
                        occurred_at=occurred_at,
                    )
        except asyncpg.UniqueViolationError as error:
            raise Conflict(
                "action_archive_slug_conflict",
                "Dieser Archiv-Slug wird bereits von einer Charity-Aktion verwendet.",
            ) from error
        return action

    async def list_latest_templates(self) -> tuple[ActionTemplate, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT DISTINCT ON (template_key)
                    template_key, version
                FROM action_template_version
                WHERE is_available
                ORDER BY template_key, version DESC
                """
            )
            templates: list[ActionTemplate] = []
            for row in rows:
                template = await self._get_template(
                    connection,
                    ActionTemplateKey(str(row["template_key"])),
                    int(row["version"]),
                )
                if template is not None:
                    templates.append(template)
            return tuple(templates)

    async def get_template(
        self,
        template_key: ActionTemplateKey,
        template_version: int | None = None,
    ) -> ActionTemplate | None:
        async with self._pool.acquire() as connection:
            return await self._get_template(
                connection,
                template_key,
                template_version,
            )

    async def get_configuration(
        self,
        action_id: UUID,
    ) -> ActionConfiguration | None:
        async with self._pool.acquire() as connection:
            return await self._get_configuration(connection, action_id)

    async def get_management(
        self,
        action_id: UUID,
    ) -> ActionManagementState | None:
        async with self._pool.acquire() as connection:
            return await self._get_management(connection, action_id)

    async def get_alias_target(
        self,
        public_alias: PublicActionAlias,
    ) -> UUID | None:
        async with self._pool.acquire() as connection:
            target = await connection.fetchval(
                "SELECT action_id FROM public_action_alias WHERE alias = $1",
                public_alias.value,
            )
            return UUID(str(target)) if target is not None else None

    async def get_by_public_alias(
        self,
        public_alias: PublicActionAlias,
    ) -> tuple[CharityAction, ActionConfiguration | None] | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read",
                readonly=True,
            ):
                action_id = await connection.fetchval(
                    """
                    SELECT action_id
                    FROM public_action_alias
                    WHERE alias = $1
                    """,
                    public_alias.value,
                )
                if action_id is None:
                    return None
                action = await self._get(connection, action_id)
                if action is None:
                    return None
                configuration = await self._get_configuration(connection, action_id)
                return action, configuration

    async def get_by_archive_slug(
        self,
        archive_slug: str,
    ) -> tuple[CharityAction, ActionConfiguration | None] | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read",
                readonly=True,
            ):
                action_id = await connection.fetchval(
                    """
                    SELECT id
                    FROM charity_action
                    WHERE archive_slug = $1
                    """,
                    archive_slug,
                )
                if action_id is None:
                    return None
                action = await self._get(connection, action_id)
                if action is None:
                    return None
                configuration = await self._get_configuration(connection, action_id)
                return action, configuration

    async def update_details(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                changed = await self._advance_revision(
                    connection,
                    action,
                    """
                    carrier_name = $3,
                    name = $4,
                    purpose = $5,
                    starts_on = $6,
                    ends_on = $7,
                    """,
                    action.carrier_name,
                    action.name,
                    action.purpose,
                    action.starts_on,
                    action.ends_on,
                    occurred_at=occurred_at,
                )
                await self._audit(
                    connection,
                    action=changed,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.details_changed",
                    request_id=request_id,
                    payload={
                        "carrierName": changed.carrier_name,
                        "name": changed.name,
                        "startsOn": changed.starts_on.isoformat(),
                        "endsOn": changed.ends_on.isoformat(),
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
        return changed

    async def replace_publication(
        self,
        action: CharityAction,
        *,
        public_alias: PublicActionAlias | None,
        allowed_previous_target_id: UUID | None,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> ActionManagementState:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(527052)")
                changed = await self._advance_revision(
                    connection,
                    action,
                    """
                    publication_starts_at = $3,
                    publication_ends_at = $4,
                    """,
                    (
                        action.publication_window.starts_at
                        if action.publication_window is not None
                        else None
                    ),
                    (
                        action.publication_window.ends_at
                        if action.publication_window is not None
                        else None
                    ),
                    occurred_at=occurred_at,
                )
                current_alias_row = await connection.fetchrow(
                    """
                    SELECT alias
                    FROM public_action_alias
                    WHERE action_id = $1
                    FOR UPDATE
                    """,
                    action.id,
                )
                current_alias = (
                    str(current_alias_row["alias"])
                    if current_alias_row is not None
                    else None
                )
                desired_alias = public_alias.value if public_alias is not None else None
                if current_alias != desired_alias:
                    previous_target_id: UUID | None = None
                    if desired_alias is not None:
                        previous_target_id = await connection.fetchval(
                            """
                            SELECT action_id
                            FROM public_action_alias
                            WHERE alias = $1
                            FOR UPDATE
                            """,
                            desired_alias,
                        )
                        if (
                            previous_target_id is not None
                            and previous_target_id != action.id
                            and previous_target_id != allowed_previous_target_id
                        ):
                            raise Conflict(
                                "action_public_alias_unavailable",
                                "Dieser öffentliche Alias ist nicht verfügbar.",
                            )
                    await connection.execute(
                        "DELETE FROM public_action_alias WHERE action_id = $1",
                        action.id,
                    )
                    if (
                        previous_target_id is not None
                        and previous_target_id != action.id
                    ):
                        await connection.execute(
                            "DELETE FROM public_action_alias WHERE alias = $1",
                            desired_alias,
                        )
                        await connection.execute(
                            """
                            UPDATE charity_action
                            SET revision = revision + 1, updated_at = $2
                            WHERE id = $1
                            """,
                            previous_target_id,
                            occurred_at,
                        )
                        await self._audit_by_id(
                            connection,
                            action_id=previous_target_id,
                            actor_user_id=actor_user_id,
                            event_type="charity_action.public_alias_released",
                            request_id=request_id,
                            payload={"publicAlias": desired_alias},
                            occurred_at=occurred_at,
                        )
                    if desired_alias is not None:
                        await connection.execute(
                            """
                            INSERT INTO public_action_alias (
                                alias, action_id, switched_at
                            )
                            VALUES ($1, $2, $3)
                            """,
                            desired_alias,
                            action.id,
                            occurred_at,
                        )
                await self._audit(
                    connection,
                    action=changed,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.publication_changed",
                    request_id=request_id,
                    payload={
                        "publicationStartsAt": (
                            changed.publication_window.starts_at.isoformat()
                            if changed.publication_window is not None
                            else None
                        ),
                        "publicationEndsAt": (
                            changed.publication_window.ends_at.isoformat()
                            if changed.publication_window is not None
                            else None
                        ),
                        "publicAlias": desired_alias,
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
                state = await self._get_management(connection, action.id)
                if state is None:
                    raise RuntimeError("Aktionsverwaltung ging nach Update verloren")
        return state

    async def replace_responsible_administrators(
        self,
        action: CharityAction,
        *,
        responsible_user_ids: frozenset[UUID],
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> ActionManagementState:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                available_rows = await connection.fetch(
                    """
                    SELECT id
                    FROM user_account
                    WHERE id = ANY($1::uuid[]) AND status = 'active'
                    FOR SHARE
                    """,
                    list(responsible_user_ids),
                )
                normalized_available_ids = frozenset(
                    row["id"] for row in available_rows
                )
                if normalized_available_ids != responsible_user_ids:
                    raise Conflict(
                        "action_responsible_administrator_unavailable",
                        "Mindestens ein ausgewähltes Mitglied ist nicht mehr verfügbar.",
                    )
                changed = await self._advance_revision(
                    connection,
                    action,
                    "",
                    occurred_at=occurred_at,
                )
                await connection.execute(
                    """
                    UPDATE action_membership
                    SET active_until = $2, updated_at = $2
                    WHERE action_id = $1
                      AND role = 'charity_admin'
                      AND active_until IS NULL
                      AND NOT (user_id = ANY($3::uuid[]))
                    """,
                    action.id,
                    occurred_at,
                    list(responsible_user_ids),
                )
                for user_id in sorted(responsible_user_ids, key=str):
                    await connection.execute(
                        """
                        INSERT INTO action_membership (
                            id, action_id, user_id, role,
                            active_from, active_until, created_at, updated_at
                        )
                        VALUES (
                            $1, $2, $3, 'charity_admin',
                            $4, NULL, $4, $4
                        )
                        ON CONFLICT (action_id, user_id, role)
                        DO UPDATE SET
                            active_from = CASE
                                WHEN action_membership.active_until IS NULL
                                THEN action_membership.active_from
                                ELSE EXCLUDED.active_from
                            END,
                            active_until = NULL,
                            updated_at = EXCLUDED.updated_at
                        """,
                        uuid4(),
                        action.id,
                        user_id,
                        occurred_at,
                    )
                await self._audit(
                    connection,
                    action=changed,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.responsibles_changed",
                    request_id=request_id,
                    payload={
                        "responsibleUserIds": [
                            str(item) for item in sorted(responsible_user_ids, key=str)
                        ],
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
                state = await self._get_management(connection, action.id)
                if state is None:
                    raise RuntimeError("Aktionsverwaltung ging nach Update verloren")
        return state

    async def update_goal(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                changed = await self._advance_revision(
                    connection,
                    action,
                    """
                    goal_value = $3,
                    actual_value = $4,
                    goal_unit = $5,
                    currency = $6,
                    """,
                    action.goal.goal_value,
                    action.goal.actual_value,
                    action.goal.unit,
                    action.goal.currency,
                    occurred_at=occurred_at,
                )
                await self._audit(
                    connection,
                    action=changed,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.goal_changed",
                    request_id=request_id,
                    payload={
                        **self._goal_payload(changed.goal),
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
        return changed

    async def replace_capabilities(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                changed = await self._advance_revision(
                    connection,
                    action,
                    "",
                    occurred_at=occurred_at,
                )
                await connection.execute(
                    "DELETE FROM charity_action_capability WHERE action_id = $1",
                    action.id,
                )
                await self._insert_capabilities(connection, action)
                await self._audit(
                    connection,
                    action=changed,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.capabilities_changed",
                    request_id=request_id,
                    payload={
                        "capabilities": self._capability_values(changed),
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
        return changed

    async def replace_beneficiaries(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                changed = await self._advance_revision(
                    connection,
                    action,
                    "",
                    occurred_at=occurred_at,
                )
                await connection.execute(
                    "DELETE FROM beneficiary WHERE action_id = $1",
                    action.id,
                )
                await self._insert_beneficiaries(connection, action, occurred_at)
                await self._audit(
                    connection,
                    action=changed,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.beneficiaries_changed",
                    request_id=request_id,
                    payload={
                        "beneficiaryCount": len(changed.beneficiaries),
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
        return changed

    async def transition(
        self,
        action: CharityAction,
        *,
        previous_status: CharityActionStatus,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                changed = await self._advance_revision(
                    connection,
                    action,
                    """
                    status = $3,
                    """,
                    action.status.value,
                    occurred_at=occurred_at,
                )
                released_alias: str | None = None
                if action.status in {
                    CharityActionStatus.COMPLETED,
                    CharityActionStatus.ARCHIVED,
                }:
                    released_alias = await connection.fetchval(
                        """
                        DELETE FROM public_action_alias
                        WHERE action_id = $1
                        RETURNING alias
                        """,
                        action.id,
                    )
                await self._audit(
                    connection,
                    action=changed,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.status_changed",
                    request_id=request_id,
                    payload={
                        "previousStatus": previous_status.value,
                        "newStatus": changed.status.value,
                        "releasedPublicAlias": released_alias,
                        "revision": changed.revision,
                    },
                    occurred_at=occurred_at,
                )
        return changed

    @staticmethod
    async def _get(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
    ) -> CharityAction | None:
        row = await connection.fetchrow(
            """
            SELECT
                id, carrier_name, name, purpose, status,
                starts_on, ends_on,
                publication_starts_at, publication_ends_at,
                archive_slug, goal_value, actual_value, goal_unit, currency,
                revision
            FROM charity_action
            WHERE id = $1
            """,
            action_id,
        )
        if row is None:
            return None
        capability_rows = await connection.fetch(
            """
            SELECT capability
            FROM charity_action_capability
            WHERE action_id = $1
            ORDER BY capability
            """,
            action_id,
        )
        beneficiary_rows = await connection.fetch(
            """
            SELECT
                id, action_id, organization_name,
                public_description, sort_order
            FROM beneficiary
            WHERE action_id = $1
            ORDER BY sort_order, id
            """,
            action_id,
        )
        return CharityAction(
            id=row["id"],
            carrier_name=str(row["carrier_name"]),
            name=str(row["name"]),
            purpose=str(row["purpose"]),
            status=CharityActionStatus(str(row["status"])),
            starts_on=row["starts_on"],
            ends_on=row["ends_on"],
            archive_slug=str(row["archive_slug"]),
            capabilities=frozenset(
                ActionCapability(str(item["capability"])) for item in capability_rows
            ),
            beneficiaries=tuple(
                Beneficiary(
                    id=item["id"],
                    action_id=item["action_id"],
                    organization_name=str(item["organization_name"]),
                    public_description=str(item["public_description"]),
                    sort_order=int(item["sort_order"]),
                )
                for item in beneficiary_rows
            ),
            goal=ActionGoal(
                goal_value=(
                    Decimal(row["goal_value"])
                    if row["goal_value"] is not None
                    else None
                ),
                actual_value=Decimal(row["actual_value"]),
                unit=str(row["goal_unit"]) if row["goal_unit"] is not None else None,
                currency=str(row["currency"]) if row["currency"] is not None else None,
            ),
            publication_window=(
                PublicationWindow(
                    starts_at=row["publication_starts_at"],
                    ends_at=row["publication_ends_at"],
                )
                if row["publication_starts_at"] is not None
                and row["publication_ends_at"] is not None
                else None
            ),
            revision=int(row["revision"]),
        )

    @staticmethod
    async def _get_configuration(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
    ) -> ActionConfiguration | None:
        snapshot_row = await connection.fetchrow(
            """
            SELECT
                template_key, template_version, display_name,
                copied_from_action_id, configuration
            FROM action_template_snapshot
            WHERE action_id = $1
            """,
            action_id,
        )
        if snapshot_row is None:
            return None
        offering_rows = await connection.fetch(
            """
            SELECT
                id, action_id, code, name, status, unit,
                allowed_quantity_units, pieces_per_unit,
                unit_price_minor, currency,
                available_from, available_until
            FROM offering
            WHERE action_id = $1
            ORDER BY code
            """,
            action_id,
        )
        form_row = await connection.fetchrow(
            """
            SELECT
                id, action_id, form_key, title, introduction, submit_label,
                require_company_name, require_contact_name, require_email,
                require_phone, require_delivery_address,
                require_billing_address, allow_message
            FROM order_form_configuration
            WHERE action_id = $1
            """,
            action_id,
        )
        snapshot_payload = snapshot_row["configuration"]
        if isinstance(snapshot_payload, str):
            snapshot_payload = json.loads(snapshot_payload)
        if not isinstance(snapshot_payload, dict):
            raise RuntimeError("Ungültiger ActionTemplate-Snapshot in PostgreSQL")
        return ActionConfiguration(
            action_id=action_id,
            snapshot=ActionTemplateSnapshot.from_payload(
                template_key=str(snapshot_row["template_key"]),
                template_version=int(snapshot_row["template_version"]),
                display_name=str(snapshot_row["display_name"]),
                copied_from_action_id=snapshot_row["copied_from_action_id"],
                payload=snapshot_payload,
            ),
            offerings=tuple(
                ConfiguredOffering(
                    id=row["id"],
                    action_id=row["action_id"],
                    definition=TemplateOffering(
                        code=str(row["code"]),
                        name=str(row["name"]),
                        status=OfferingStatus(str(row["status"])),
                        unit=OfferingUnit(str(row["unit"])),
                        pieces_per_unit=(
                            int(row["pieces_per_unit"])
                            if row["pieces_per_unit"] is not None
                            else None
                        ),
                        unit_price_minor=int(row["unit_price_minor"]),
                        currency=str(row["currency"]),
                    ),
                    allowed_quantity_units=frozenset(
                        OfferingUnit(str(value))
                        for value in row["allowed_quantity_units"]
                    ),
                    available_from=row["available_from"],
                    available_until=row["available_until"],
                )
                for row in offering_rows
            ),
            order_form=(
                ConfiguredOrderForm(
                    id=form_row["id"],
                    action_id=form_row["action_id"],
                    configuration=AsyncpgCharityActionRepository._order_form_from_row(
                        form_row
                    ),
                )
                if form_row is not None
                else None
            ),
        )

    @staticmethod
    async def _get_management(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
    ) -> ActionManagementState | None:
        action = await AsyncpgCharityActionRepository._get(connection, action_id)
        if action is None:
            return None
        alias = await connection.fetchval(
            "SELECT alias FROM public_action_alias WHERE action_id = $1",
            action_id,
        )
        administrator_rows = await connection.fetch(
            """
            SELECT
                account.id,
                account.display_name,
                account.email,
                account.status = 'active' AS is_available,
                EXISTS (
                    SELECT 1
                    FROM action_membership AS membership
                    WHERE membership.action_id = $1
                      AND membership.user_id = account.id
                      AND membership.role = 'charity_admin'
                      AND membership.active_from <= CURRENT_TIMESTAMP
                      AND (
                        membership.active_until IS NULL
                        OR membership.active_until > CURRENT_TIMESTAMP
                      )
                ) AS is_responsible
            FROM user_account AS account
            WHERE account.status = 'active'
               OR EXISTS (
                    SELECT 1
                    FROM action_membership AS membership
                    WHERE membership.action_id = $1
                      AND membership.user_id = account.id
                      AND membership.role = 'charity_admin'
                      AND membership.active_from <= CURRENT_TIMESTAMP
                      AND (
                        membership.active_until IS NULL
                        OR membership.active_until > CURRENT_TIMESTAMP
                      )
               )
            ORDER BY lower(account.display_name), account.id
            """,
            action_id,
        )
        return ActionManagementState(
            action=action,
            public_alias=(PublicActionAlias(str(alias)) if alias is not None else None),
            administrator_options=tuple(
                AdministratorOption(
                    user_id=row["id"],
                    display_name=str(row["display_name"]),
                    email=str(row["email"]),
                    is_available=bool(row["is_available"]),
                    is_responsible=bool(row["is_responsible"]),
                )
                for row in administrator_rows
            ),
        )

    @staticmethod
    async def _get_template(
        connection: asyncpg.Connection[Any],
        template_key: ActionTemplateKey,
        template_version: int | None,
    ) -> ActionTemplate | None:
        row = await connection.fetchrow(
            """
            SELECT template_key, version, display_name, description
            FROM action_template_version
            WHERE template_key = $1
              AND ($2::integer IS NULL OR version = $2)
              AND is_available
            ORDER BY version DESC
            LIMIT 1
            """,
            template_key.value,
            template_version,
        )
        if row is None:
            return None
        version = int(row["version"])
        capabilities = await connection.fetch(
            """
            SELECT capability
            FROM action_template_capability
            WHERE template_key = $1 AND template_version = $2
            ORDER BY capability
            """,
            template_key.value,
            version,
        )
        offerings = await connection.fetch(
            """
            SELECT
                code, name, status, unit, pieces_per_unit,
                unit_price_minor, currency
            FROM action_template_offering
            WHERE template_key = $1 AND template_version = $2
            ORDER BY sort_order, code
            """,
            template_key.value,
            version,
        )
        form = await connection.fetchrow(
            """
            SELECT
                form_key, title, introduction, submit_label,
                require_company_name, require_contact_name, require_email,
                require_phone, require_delivery_address,
                require_billing_address, allow_message
            FROM action_template_order_form
            WHERE template_key = $1 AND template_version = $2
            """,
            template_key.value,
            version,
        )
        return ActionTemplate(
            key=template_key,
            version=version,
            display_name=str(row["display_name"]),
            description=str(row["description"]),
            capabilities=frozenset(
                ActionCapability(str(item["capability"])) for item in capabilities
            ),
            offerings=tuple(
                TemplateOffering(
                    code=str(item["code"]),
                    name=str(item["name"]),
                    status=OfferingStatus(str(item["status"])),
                    unit=OfferingUnit(str(item["unit"])),
                    pieces_per_unit=(
                        int(item["pieces_per_unit"])
                        if item["pieces_per_unit"] is not None
                        else None
                    ),
                    unit_price_minor=int(item["unit_price_minor"]),
                    currency=str(item["currency"]),
                )
                for item in offerings
            ),
            order_form=(
                AsyncpgCharityActionRepository._order_form_from_row(form)
                if form is not None
                else None
            ),
        )

    @staticmethod
    async def _insert_capabilities(
        connection: asyncpg.Connection[Any],
        action: CharityAction,
    ) -> None:
        if not action.capabilities:
            return
        await connection.executemany(
            """
            INSERT INTO charity_action_capability (action_id, capability)
            VALUES ($1, $2)
            """,
            [
                (action.id, capability.value)
                for capability in sorted(
                    action.capabilities, key=lambda item: item.value
                )
            ],
        )

    @staticmethod
    async def _insert_beneficiaries(
        connection: asyncpg.Connection[Any],
        action: CharityAction,
        occurred_at: datetime,
    ) -> None:
        await connection.executemany(
            """
            INSERT INTO beneficiary (
                id, action_id, organization_name, public_description,
                sort_order, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $6)
            """,
            [
                (
                    item.id,
                    item.action_id,
                    item.organization_name,
                    item.public_description,
                    item.sort_order,
                    occurred_at,
                )
                for item in action.beneficiaries
            ],
        )

    @staticmethod
    async def _insert_configuration(
        connection: asyncpg.Connection[Any],
        configuration: ActionConfiguration,
        occurred_at: datetime,
    ) -> None:
        snapshot = configuration.snapshot
        await connection.execute(
            """
            INSERT INTO action_template_snapshot (
                action_id, template_key, template_version, display_name,
                copied_from_action_id, configuration, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            """,
            configuration.action_id,
            snapshot.template_key.value,
            snapshot.template_version,
            snapshot.display_name,
            snapshot.copied_from_action_id,
            json.dumps(snapshot.payload(), separators=(",", ":")),
            occurred_at,
        )
        if configuration.offerings:
            await connection.executemany(
                """
                INSERT INTO offering (
                    id, action_id, code, name, status, unit,
                    allowed_quantity_units, pieces_per_unit,
                    unit_price_minor, currency,
                    available_from, available_until,
                    created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9,
                    $10, $11, $12, $13, $13
                )
                """,
                [
                    (
                        item.id,
                        item.action_id,
                        item.definition.code,
                        item.definition.name,
                        item.definition.status.value,
                        item.definition.unit.value,
                        [value.value for value in item.allowed_quantity_units],
                        item.definition.pieces_per_unit,
                        item.definition.unit_price_minor,
                        item.definition.currency,
                        item.available_from,
                        item.available_until,
                        occurred_at,
                    )
                    for item in configuration.offerings
                ],
            )
        if configuration.order_form is not None:
            form = configuration.order_form
            value = form.configuration
            await connection.execute(
                """
                INSERT INTO order_form_configuration (
                    id, action_id, form_key, status, title, introduction,
                    submit_label, require_company_name, require_contact_name,
                    require_email, require_phone, require_delivery_address,
                    require_billing_address, allow_message, created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, 'draft', $4, $5,
                    $6, $7, $8,
                    $9, $10, $11,
                    $12, $13, $14, $14
                )
                """,
                form.id,
                form.action_id,
                value.form_key,
                value.title,
                value.introduction,
                value.submit_label,
                value.require_company_name,
                value.require_contact_name,
                value.require_email,
                value.require_phone,
                value.require_delivery_address,
                value.require_billing_address,
                value.allow_message,
                occurred_at,
            )

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        action: CharityAction,
        actor_user_id: UUID,
        event_type: str,
        request_id: str,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        await AsyncpgCharityActionRepository._audit_by_id(
            connection,
            action_id=action.id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            request_id=request_id,
            payload=payload,
            occurred_at=occurred_at,
        )

    @staticmethod
    async def _audit_by_id(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID,
        event_type: str,
        request_id: str,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type,
                entity_type, entity_id, request_id, payload, occurred_at
            )
            VALUES (
                $1, $2, $3, $4,
                'charity_action', $2, $5, $6::jsonb, $7
            )
            """,
            uuid4(),
            action_id,
            actor_user_id,
            event_type,
            request_id,
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )

    @staticmethod
    async def _advance_revision(
        connection: asyncpg.Connection[Any],
        action: CharityAction,
        assignments: str,
        *values: object,
        occurred_at: datetime,
    ) -> CharityAction:
        occurred_at_parameter = len(values) + 3
        revision = await connection.fetchval(
            f"""
            UPDATE charity_action
            SET {assignments}
                revision = revision + 1,
                updated_at = ${occurred_at_parameter}
            WHERE id = $1 AND revision = $2
            RETURNING revision
            """,
            action.id,
            action.revision,
            *values,
            occurred_at,
        )
        if revision is None:
            raise Conflict(
                "action_revision_conflict",
                "Die Charity-Aktion wurde zwischenzeitlich geändert. "
                "Lade den aktuellen Stand und prüfe deine Eingaben erneut.",
            )
        changed = action.next_revision()
        if int(revision) != changed.revision:
            raise RuntimeError("PostgreSQL lieferte eine unerwartete Aktionsrevision")
        return changed

    @staticmethod
    def _capability_values(action: CharityAction) -> list[str]:
        return sorted(item.value for item in action.capabilities)

    @staticmethod
    def _goal_payload(goal: ActionGoal) -> dict[str, object]:
        return {
            "goalValue": str(goal.goal_value) if goal.goal_value is not None else None,
            "actualValue": str(goal.actual_value),
            "unit": goal.unit,
            "currency": goal.currency,
        }

    @staticmethod
    def _snapshot_reference(
        configuration: ActionConfiguration,
    ) -> dict[str, object]:
        snapshot = configuration.snapshot
        return {
            "key": snapshot.template_key.value,
            "version": snapshot.template_version,
            "copiedFromActionId": (
                str(snapshot.copied_from_action_id)
                if snapshot.copied_from_action_id is not None
                else None
            ),
        }

    @staticmethod
    def _order_form_from_row(
        row: asyncpg.Record,
    ) -> OrderFormConfiguration:
        return OrderFormConfiguration(
            form_key=str(row["form_key"]),
            title=str(row["title"]),
            introduction=str(row["introduction"]),
            submit_label=str(row["submit_label"]),
            require_company_name=bool(row["require_company_name"]),
            require_contact_name=bool(row["require_contact_name"]),
            require_email=bool(row["require_email"]),
            require_phone=bool(row["require_phone"]),
            require_delivery_address=bool(row["require_delivery_address"]),
            require_billing_address=bool(row["require_billing_address"]),
            allow_message=bool(row["allow_message"]),
        )

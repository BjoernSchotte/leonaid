"""Material-owned PostgreSQL state using the existing private object storage port."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import hashlib
import json
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import asyncpg

from leonaid.adapters.postgres.action_progress import AsyncpgCommandReceiptRepository
from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    DependencyUnavailable,
    ResourceNotFound,
)
from leonaid.application.object_storage import (
    ObjectStorage,
    ObjectLocation,
    ObjectWrite,
    ObjectStorageError,
    ObjectStorageConflict,
    ObjectDeletionAuthorization,
)
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.materials.api import (
    CreateMaterial,
    CleanupUpload,
    AddVersion,
    Material,
    MaterialVersion,
    MaterialDownload,
    MaterialQuery,
    Materials,
    upload_digest,
    MemberQuery,
    SetMaterialMember,
    SetMaterialMemberByEmail,
    MaterialAccess,
    MaterialMember,
    MaterialMembers,
    MaterialPermissions,
)

_READ_ACCESS = """
    ((m.action_id IS NULL AND (m.owner_user_id=$1 OR EXISTS (
        SELECT 1 FROM material_member a WHERE a.material_id=m.id AND a.user_id=$1)))
    OR (m.action_id IS NOT NULL AND (
        EXISTS (SELECT 1 FROM user_global_role g WHERE g.user_id=$1 AND g.role='system_admin')
        OR EXISTS (SELECT 1 FROM action_membership a WHERE a.user_id=$1 AND a.action_id=m.action_id
            AND a.active_from<=now() AND (a.active_until IS NULL OR a.active_until>now())))))
"""
_FIELDS = "m.id,m.action_id,m.owner_user_id,m.title,m.revision,m.current_version"


class AsyncpgMaterialRepository:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        storage: ObjectStorage | None = None,
        *,
        connection: asyncpg.Connection[Any] | None = None,
    ) -> None:
        self.pool = pool
        self._storage = storage
        self.connection = connection

    @property
    def storage(self) -> ObjectStorage:
        # Metadata-only module calls do not need object-storage credentials.
        if self._storage is None:
            raise DependencyUnavailable(
                "material_storage_unavailable", "Dateispeicher ist nicht konfiguriert."
            )
        return self._storage

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[asyncpg.Connection[Any]]:
        if self.connection is not None:
            yield self.connection
        else:
            async with self.pool.acquire() as conn:
                yield conn

    async def _active(
        self, conn: asyncpg.Connection[Any], actor: IdentityPrincipal
    ) -> None:
        if (
            await conn.fetchval(
                "SELECT status FROM user_account WHERE id=$1 FOR SHARE",
                actor.account.id,
            )
            != "active"
        ):
            raise AuthenticationRequired(
                "authentication_required", "Aktives Konto erforderlich."
            )

    async def _action_write(
        self, conn: asyncpg.Connection[Any], user_id: UUID, action_id: UUID
    ) -> bool:
        return bool(
            await conn.fetchval(
                """
            SELECT EXISTS (SELECT 1 FROM charity_action a WHERE a.id=$2 AND (
                EXISTS (SELECT 1 FROM user_global_role WHERE user_id=$1 AND role='system_admin')
                OR EXISTS (SELECT 1 FROM action_membership WHERE user_id=$1 AND action_id=a.id
                    AND role='charity_admin' AND active_from<=now()
                    AND (active_until IS NULL OR active_until>now()))))
        """,
                user_id,
                action_id,
            )
        )

    async def _material(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        material_id: UUID,
        *,
        write: bool = False,
    ) -> Material:
        lock = "UPDATE" if write else "SHARE"
        row = await conn.fetchrow(
            f"SELECT {_FIELDS} FROM material m WHERE m.id=$2 AND {_READ_ACCESS} FOR {lock} OF m",
            actor.account.id,
            material_id,
        )
        if row is None:
            raise ResourceNotFound("not_found", "Material nicht gefunden.")
        material = Material.model_validate(dict(row))
        if (
            write
            and not (
                await self._permissions(
                    conn,
                    actor.account.id,
                    material_id,
                    material.owner_user_id,
                    material.action_id,
                )
            ).can_edit
        ):
            raise ResourceNotFound("not_found", "Material nicht gefunden.")
        return material

    async def _receipt(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        context: UUID,
        operation: str,
        command: CreateMaterial
        | AddVersion
        | SetMaterialMember
        | SetMaterialMemberByEmail,
        content: bytes | None = None,
    ) -> tuple[str, dict[str, str] | None, str]:
        key = f"materials:{actor.account.id}:{operation}:{context}:{command.idempotency_key}"
        payload = command.model_dump_json()
        if content is not None:
            payload += ":" + upload_digest(content)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        try:
            replay = await AsyncpgCommandReceiptRepository(conn).reserve(
                idempotency_key=key, command_type=operation, request_hash=digest
            )
        except ApplicationError as error:
            if error.code == "idempotency_conflict":
                raise Conflict(error.code, error.message) from error
            raise
        return key, replay, digest

    async def _lock_upload(
        self, conn: asyncpg.Connection[Any], location: ObjectLocation
    ) -> None:
        # Same transaction lock for uploader and cleanup; includes an outer caller transaction.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            f"materials:object:{location.bucket}:{location.key}",
        )

    async def _cleanup_admin(
        self, conn: asyncpg.Connection[Any], actor: IdentityPrincipal
    ) -> None:
        await self._active(conn, actor)
        if not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM user_global_role WHERE user_id=$1 AND role='system_admin')",
            actor.account.id,
        ):
            raise ResourceNotFound("not_found", "Materialwartung nicht verfügbar.")

    async def cleanup_upload(
        self, actor: IdentityPrincipal, command: CleanupUpload
    ) -> bool:
        if self.connection is not None:
            raise ValueError(
                "Upload-Bereinigung benötigt einen eigenen Transaktionsrahmen."
            )
        location = ObjectLocation(
            self.storage.bucket,
            f"materials/{command.material_id}/{command.upload_id}",
            command.storage_version_id,
        )
        attempt_id = uuid4()
        async with self.pool.acquire() as conn:
            if command.apply:
                # Persist intention before external deletion; a crash leaves an auditable attempt.
                async with conn.transaction():
                    await self._cleanup_admin(conn, actor)
                    await conn.execute(
                        "INSERT INTO audit_event(id,actor_user_id,event_type,entity_type,entity_id,request_id,payload) VALUES ($1,$2,'material.upload_cleanup_requested','material',$3,$4,$5::jsonb)",
                        attempt_id,
                        actor.account.id,
                        command.material_id,
                        str(attempt_id),
                        json.dumps(command.model_dump(mode="json")),
                    )
            async with conn.transaction():
                await self._cleanup_admin(conn, actor)
                await self._lock_upload(conn, location)
                if await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM material_version WHERE storage_bucket=$1 AND object_key=$2 AND storage_version_id=$3)",
                    location.bucket,
                    location.key,
                    location.version_id,
                ):
                    raise Conflict(
                        "material_upload_referenced",
                        "Diese Dateiversion wird verwendet und darf nicht bereinigt werden.",
                    )
                try:
                    stored = await self.storage.head(location)
                    if stored is not None and stored.metadata.get("material-id") != str(
                        command.material_id
                    ):
                        raise Conflict(
                            "material_upload_mismatch",
                            "Die Dateiversion gehört nicht zum angegebenen Material.",
                        )
                    if stored is not None and command.apply:
                        await self.storage.delete(
                            location,
                            authorization=ObjectDeletionAuthorization(
                                actor.account.id, command.reason
                            ),
                        )
                except ObjectStorageError as error:
                    raise DependencyUnavailable(
                        "material_storage_unavailable",
                        "Die Upload-Bereinigung konnte nicht bestätigt werden. Wiederhole denselben Aufruf.",
                    ) from error
                if command.apply:
                    await conn.execute(
                        "INSERT INTO audit_event(id,actor_user_id,event_type,entity_type,entity_id,request_id,payload) VALUES ($1,$2,'material.upload_cleanup_completed','material',$3,$4,'{}'::jsonb)",
                        uuid4(),
                        actor.account.id,
                        command.material_id,
                        str(attempt_id),
                    )
                return stored is not None

    async def _store_version(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        material: Material,
        command: CreateMaterial | AddVersion,
        content: bytes,
        key: str,
        digest: str,
    ) -> None:
        location = ObjectLocation(
            bucket=self.storage.bucket,
            key=f"materials/{material.id}/{uuid5(NAMESPACE_URL, key)}",
        )
        await self._lock_upload(conn, location)
        try:
            stored = await self.storage.put_immutable(
                ObjectWrite(
                    location=location,
                    content=content,
                    media_type=command.media_type,
                    sha256=upload_digest(content),
                    metadata={"material-id": str(material.id), "request-hash": digest},
                )
            )
            retrieved = await self.storage.get(stored.location)
            if retrieved.content != content or retrieved.stored != stored:
                raise DependencyUnavailable(
                    "material_integrity_failed",
                    "Die gespeicherte Datei ist nicht byteidentisch lesbar.",
                )
        except ObjectStorageConflict as error:
            raise Conflict(
                "idempotency_conflict",
                "Dieser Upload-Schlüssel wurde bereits für andere Dateidaten verwendet.",
            ) from error
        except ObjectStorageError as error:
            raise DependencyUnavailable(
                "material_storage_unavailable",
                "Die Datei konnte nicht sicher gespeichert werden. Wiederhole denselben Upload.",
            ) from error
        await conn.execute(
            """
            INSERT INTO material_version(material_id,version,filename,media_type,size_bytes,sha256,
                storage_bucket,object_key,storage_version_id,created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """,
            material.id,
            material.current_version,
            command.filename,
            stored.media_type,
            stored.size_bytes,
            stored.sha256,
            stored.location.bucket,
            stored.location.key,
            stored.location.version_id,
            actor.account.id,
        )

    async def _finish(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        material: Material,
        key: str,
        operation: str,
        result: dict[str, str] | None = None,
    ) -> None:
        await conn.execute(
            """INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
            VALUES ($1,$2,$3,$4,'material',$5,$6,'{}'::jsonb)""",
            uuid4(),
            material.action_id,
            actor.account.id,
            operation,
            material.id,
            key,
        )
        await AsyncpgCommandReceiptRepository(conn).complete(
            idempotency_key=key,
            result=result or {"material": material.model_dump_json()},
        )

    async def create_material(
        self, actor: IdentityPrincipal, command: CreateMaterial, content: bytes
    ) -> Material:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            if command.action_id is not None and not await self._action_write(
                conn, actor.account.id, command.action_id
            ):
                raise ResourceNotFound("not_found", "Aktion nicht verfügbar.")
            operation = "material.created"
            key, replay, digest = await self._receipt(
                conn,
                actor,
                command.action_id or actor.account.id,
                operation,
                command,
                content,
            )
            if replay:
                material = Material.model_validate_json(replay["material"])
                await self._material(conn, actor, material.id, write=True)
                return material
            material = Material(
                id=uuid5(NAMESPACE_URL, key),
                action_id=command.action_id,
                owner_user_id=actor.account.id,
                title=command.title,
                revision=1,
                current_version=1,
            )
            await conn.execute(
                "INSERT INTO material(id,action_id,owner_user_id,title) VALUES ($1,$2,$3,$4)",
                material.id,
                material.action_id,
                material.owner_user_id,
                material.title,
            )
            await self._store_version(
                conn, actor, material, command, content, key, digest
            )
            await self._finish(conn, actor, material, key, operation)
            return material

    async def add_version(
        self,
        actor: IdentityPrincipal,
        material_id: UUID,
        command: AddVersion,
        content: bytes,
    ) -> Material:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            current = await self._material(conn, actor, material_id, write=True)
            operation = "material.version_added"
            key, replay, digest = await self._receipt(
                conn, actor, material_id, operation, command, content
            )
            if replay:
                return Material.model_validate_json(replay["material"])
            if command.expected_revision != current.revision:
                raise Conflict(
                    "revision_conflict", "Das Material wurde inzwischen geändert."
                )
            material = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "current_version": current.current_version + 1,
                }
            )
            await self._store_version(
                conn, actor, material, command, content, key, digest
            )
            await conn.execute(
                "UPDATE material SET revision=$2,current_version=$3,updated_at=now() WHERE id=$1",
                material.id,
                material.revision,
                material.current_version,
            )
            await self._finish(conn, actor, material, key, operation)
            return material

    async def get_material(
        self, actor: IdentityPrincipal, material_id: UUID
    ) -> Material:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            return await self._material(conn, actor, material_id)

    async def _version(
        self, conn: asyncpg.Connection[Any], material_id: UUID, version: int
    ) -> asyncpg.Record:
        row = await conn.fetchrow(
            "SELECT * FROM material_version WHERE material_id=$1 AND version=$2",
            material_id,
            version,
        )
        if row is None:
            raise ResourceNotFound("not_found", "Dateiversion nicht gefunden.")
        return row

    def _public_version(self, row: asyncpg.Record) -> MaterialVersion:
        return MaterialVersion.model_validate(
            {field: row[field] for field in MaterialVersion.model_fields}
        )

    async def get_version(
        self, actor: IdentityPrincipal, material_id: UUID, version: int
    ) -> MaterialVersion:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            await self._material(conn, actor, material_id)
            return self._public_version(await self._version(conn, material_id, version))

    async def download(
        self, actor: IdentityPrincipal, material_id: UUID, version: int
    ) -> MaterialDownload:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            await self._material(conn, actor, material_id)
            row = await self._version(conn, material_id, version)
            metadata = self._public_version(row)
            try:
                retrieved = await self.storage.get(
                    ObjectLocation(
                        bucket=row["storage_bucket"],
                        key=row["object_key"],
                        version_id=row["storage_version_id"],
                    )
                )
            except ObjectStorageError as error:
                raise DependencyUnavailable(
                    "material_storage_unavailable",
                    "Die Dateiversion ist momentan nicht sicher abrufbar.",
                ) from error
            if (
                retrieved.stored.sha256 != metadata.sha256
                or retrieved.stored.size_bytes != metadata.size_bytes
                or retrieved.stored.media_type != metadata.media_type
                or upload_digest(retrieved.content) != metadata.sha256
            ):
                raise DependencyUnavailable(
                    "material_integrity_failed",
                    "Die Dateiversion verletzt ihre gespeicherten Integritätsdaten.",
                )
            return MaterialDownload(version=metadata, content=retrieved.content)

    async def list_materials(
        self, actor: IdentityPrincipal, query: MaterialQuery
    ) -> Materials:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            rows = await conn.fetch(
                f"""SELECT {_FIELDS} FROM material m
                WHERE {_READ_ACCESS} AND ($2::uuid IS NULL OR m.action_id=$2)
                AND strpos(lower(m.title),lower($3))>0 ORDER BY lower(m.title),m.id LIMIT $4 OFFSET $5""",
                actor.account.id,
                query.action_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return Materials(
                items=[
                    Material.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def _manage_material(
        self,
        conn: asyncpg.Connection[Any],
        actor: IdentityPrincipal,
        material_id: UUID,
        *,
        write: bool,
    ) -> Material:
        material = await self._material(conn, actor, material_id, write=write)
        if not (
            await self._permissions(
                conn,
                actor.account.id,
                material_id,
                material.owner_user_id,
                material.action_id,
            )
        ).can_manage:
            raise ResourceNotFound("not_found", "Materialverwaltung nicht verfügbar.")
        return material

    async def set_material_member(
        self,
        actor: IdentityPrincipal,
        material_id: UUID,
        command: SetMaterialMember | SetMaterialMemberByEmail,
    ) -> MaterialAccess:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            material = await self._manage_material(conn, actor, material_id, write=True)
            operation = "material.member_changed"
            key, replay, _digest = await self._receipt(
                conn, actor, material_id, operation, command
            )
            if replay:
                return MaterialAccess.model_validate_json(replay["material"])
            revision = await conn.fetchval(
                "SELECT access_revision FROM material WHERE id=$1", material_id
            )
            if revision != command.expected_access_revision:
                raise Conflict(
                    "revision_conflict",
                    "Die Materialrechte wurden inzwischen geändert.",
                )
            if isinstance(command, SetMaterialMemberByEmail):
                user_id = await conn.fetchval(
                    "SELECT id FROM user_account WHERE lower(email)=lower($1) AND status='active'",
                    str(command.email),
                )
                if user_id is None:
                    raise Conflict(
                        "material_member_invalid",
                        "Dieses Konto kann nicht hinzugefügt werden.",
                    )
            else:
                user_id = command.user_id
            if user_id == material.owner_user_id:
                raise Conflict(
                    "material_owner_protected",
                    "Der Eigentümer kann nicht entfernt oder herabgestuft werden.",
                )
            if command.access is not None:
                if not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM user_account WHERE id=$1 AND status='active')",
                    user_id,
                ):
                    raise Conflict(
                        "material_member_invalid",
                        "Dieses Konto kann nicht hinzugefügt werden.",
                    )
                if material.action_id is not None and not await conn.fetchval(
                    f"SELECT EXISTS (SELECT 1 FROM material m WHERE m.id=$2 AND {_READ_ACCESS})",
                    user_id,
                    material_id,
                ):
                    raise Conflict(
                        "material_member_invalid", "Aktionszugriff erforderlich."
                    )
                await conn.execute(
                    "INSERT INTO material_member(material_id,user_id,access) VALUES ($1,$2,$3) ON CONFLICT(material_id,user_id) DO UPDATE SET access=EXCLUDED.access",
                    material_id,
                    user_id,
                    command.access,
                )
            else:
                await conn.execute(
                    "DELETE FROM material_member WHERE material_id=$1 AND user_id=$2",
                    material_id,
                    user_id,
                )
            revision = await conn.fetchval(
                "UPDATE material SET access_revision=access_revision+1 WHERE id=$1 RETURNING access_revision",
                material_id,
            )
            result = MaterialAccess(
                owner_user_id=material.owner_user_id, access_revision=revision
            )
            await self._finish(
                conn,
                actor,
                material,
                key,
                operation,
                result={"material": result.model_dump_json()},
            )
            return result

    async def list_members(
        self, actor: IdentityPrincipal, material_id: UUID, query: MemberQuery
    ) -> MaterialMembers:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            material = await self._manage_material(
                conn, actor, material_id, write=False
            )
            revision = await conn.fetchval(
                "SELECT access_revision FROM material WHERE id=$1", material_id
            )
            rows = await conn.fetch(
                "SELECT m.user_id,u.display_name,m.access,(u.status='active') AS active FROM material_member m JOIN user_account u ON u.id=m.user_id WHERE m.material_id=$1 AND strpos(lower(u.display_name),lower($2))>0 ORDER BY m.user_id LIMIT $3 OFFSET $4",
                material_id,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return MaterialMembers(
                owner_user_id=material.owner_user_id,
                access_revision=revision,
                items=[
                    MaterialMember.model_validate(dict(row))
                    for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def _permissions(
        self,
        conn: asyncpg.Connection[Any],
        user_id: UUID,
        material_id: UUID,
        owner_user_id: UUID,
        action_id: UUID | None,
    ) -> MaterialPermissions:
        # Call only after the material read policy has passed; ownership never bypasses action access.
        manage = owner_user_id == user_id or (
            action_id is not None and await self._action_write(conn, user_id, action_id)
        )
        edit = manage or bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM material_member WHERE material_id=$1 AND user_id=$2 AND access='editor')",
                material_id,
                user_id,
            )
        )
        return MaterialPermissions(can_edit=edit, can_manage=manage)

    async def get_permissions(
        self, actor: IdentityPrincipal, material_id: UUID
    ) -> MaterialPermissions:
        async with self._connection() as conn, conn.transaction():
            await self._active(conn, actor)
            material = await self._material(conn, actor, material_id, write=False)
            return await self._permissions(
                conn,
                actor.account.id,
                material_id,
                material.owner_user_id,
                material.action_id,
            )

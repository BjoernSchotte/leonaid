"""Site hosts and edition bindings in PostgreSQL (specs/multi-domain §7.3).

Every command runs in one transaction under one advisory lock, checks the
system-admin role at the start and at the end, writes an audit event per
changed row and a command receipt for the idempotent command id. The
partial unique indexes of migration 0055 are the last line of defence for
"one root per host", "one live segment per host", "an action once per host"
and "one primary binding per action".
"""

from __future__ import annotations

import json
import secrets
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.application.site_hosts import (
    AddSiteHost,
    BindableAction,
    BindEdition,
    ChangeEditionSegment,
    MoveRootToEdition,
    RemovalPreview,
    RemovalPreviewItem,
    RemoveSiteHost,
    SetPrimaryEdition,
    SetRedirectHost,
    SiteBindingView,
    SiteHostCommand,
    SiteHostOverview,
    SiteHostView,
    UnbindEdition,
    command_fingerprint,
)
from leonaid.domain.site_hosts import (
    ConfiguredHosts,
    EditionAvailability,
    LiveEdition,
    SiteHostStatus,
    canonical_url,
    default_edition_segment,
    display_hostname,
    edition_availability,
    edition_url,
    public_host_path,
)

# One lock for every site host change: few writes, no lock-order puzzles.
SITE_HOST_LOCK = 527061
BUSY = (
    asyncpg.LockNotAvailableError,
    asyncpg.QueryCanceledError,
    asyncpg.DeadlockDetectedError,
)

_ACTION_COLUMNS = """
    a.id AS action_id, a.name AS action_name, a.archive_slug, a.status AS action_status,
    a.publication_starts_at, a.publication_ends_at, a.starts_on, a.ends_on,
    alias.alias AS primary_alias,
    COALESCE(alias.campaign_redirect, false) AS campaign_page
"""
_ALIAS_JOIN = """
    LEFT JOIN public_action_alias AS alias
      ON alias.action_id = a.id AND alias.is_primary AND alias.enabled
"""
_BINDING_SELECT = f"""
    SELECT b.id, b.site_host_id, b.edition_segment, b.at_root, b.is_primary,
           b.valid_from, b.valid_to, b.ended_reason, b.revision,
           h.hostname, h.status AS host_status, {_ACTION_COLUMNS}
    FROM site_binding AS b
    JOIN site_host AS h ON h.id = b.site_host_id
    JOIN charity_action AS a ON a.id = b.action_id
    {_ALIAS_JOIN}
"""


def availability_of(
    row: asyncpg.Record | dict[str, Any], now: datetime
) -> EditionAvailability:
    starts = row["publication_starts_at"]
    ends = row["publication_ends_at"]
    return edition_availability(
        status=row["action_status"],
        published_now=row["action_status"] == "active"
        and starts is not None
        and ends is not None
        and starts <= now <= ends,
    )


def live_edition(row: asyncpg.Record, now: datetime) -> LiveEdition:
    return LiveEdition(
        hostname=row["hostname"],
        host_status=SiteHostStatus(row["host_status"]),
        segment=row["edition_segment"],
        at_root=row["at_root"],
        is_primary=row["is_primary"],
        availability=availability_of(row, now),
        bound_at=row["valid_from"],
    )


@dataclass(frozen=True, slots=True)
class CanonicalResolver:
    """The canonical URL function of §7.7.3 over the database."""

    configured: ConfiguredHosts
    site_base_url: str

    def public_fallback(
        self, row: asyncpg.Record | dict[str, Any], now: datetime
    ) -> str | None:
        if not self.configured.has_public_host:
            return None
        return self.site_base_url.rstrip("/") + public_host_path(
            archive_slug=row["archive_slug"],
            primary_alias=row["primary_alias"],
            campaign_page=row["campaign_page"],
            availability=availability_of(row, now),
        )

    async def for_actions(
        self,
        db: asyncpg.Connection[Any],
        action_ids: Iterable[UUID],
        now: datetime,
        *,
        exclude_host_id: UUID | None = None,
    ) -> dict[UUID, str | None]:
        ids = sorted(set(action_ids))
        if not ids:
            return {}
        actions = await db.fetch(
            f"SELECT {_ACTION_COLUMNS} FROM charity_action AS a {_ALIAS_JOIN} "
            "WHERE a.id = ANY($1::uuid[])",
            ids,
        )
        bindings = await db.fetch(
            _BINDING_SELECT
            + " WHERE b.action_id = ANY($1::uuid[]) AND b.valid_to IS NULL"
            " AND ($2::uuid IS NULL OR b.site_host_id <> $2)",
            ids,
            exclude_host_id,
        )
        live: dict[UUID, list[LiveEdition]] = defaultdict(list)
        for row in bindings:
            live[row["action_id"]].append(live_edition(row, now))
        return {
            row["action_id"]: canonical_url(
                live[row["action_id"]],
                public_fallback_url=self.public_fallback(row, now),
            )
            for row in actions
        }


def _binding_view(
    row: asyncpg.Record, now: datetime, target_url: str | None = None
) -> SiteBindingView:
    edition = live_edition(row, now)
    return SiteBindingView(
        id=row["id"],
        action_id=row["action_id"],
        action_name=row["action_name"],
        archive_slug=row["archive_slug"],
        segment=row["edition_segment"],
        at_root=row["at_root"],
        is_primary=row["is_primary"],
        availability=edition.availability,
        edition_url=edition_url(edition),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        ended_reason=row["ended_reason"],
        revision=row["revision"],
        target_url=target_url,
        campaign_page=row["campaign_page"],
    )


class AsyncpgSiteHostRepository:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        canonical: CanonicalResolver,
    ) -> None:
        self._pool = pool
        self._canonical = canonical

    # ---------- reads ----------

    async def overview(self, actor_id: UUID) -> SiteHostOverview:
        try:
            async with self._pool.acquire() as db:
                async with db.transaction(isolation="repeatable_read"):
                    await db.execute("SET LOCAL statement_timeout='5s'")
                    await self._authority(db, actor_id)
                    now = datetime.now(timezone.utc)
                    hosts = await self._views(db, None, now)
                    rows = await db.fetch(
                        f"SELECT {_ACTION_COLUMNS} FROM charity_action AS a {_ALIAS_JOIN} "
                        "ORDER BY a.status IN ('completed','archived'), "
                        "a.publication_starts_at DESC NULLS LAST, a.name, a.id"
                    )
                    actions = tuple(
                        BindableAction(
                            id=row["action_id"],
                            name=row["action_name"],
                            archive_slug=row["archive_slug"],
                            status=row["action_status"],
                            availability=availability_of(row, now),
                            campaign_page=row["campaign_page"],
                        )
                        for row in rows
                    )
                    return SiteHostOverview(
                        configured=self._canonical.configured,
                        hosts=tuple(hosts),
                        actions=actions,
                    )
        except BUSY:
            raise _busy() from None

    async def host(self, host_id: UUID) -> SiteHostView:
        async with self._pool.acquire() as db:
            views = await self._views(db, [host_id], datetime.now(timezone.utc))
        if not views:
            raise _host_not_found()
        return views[0]

    async def removal_preview(self, actor_id: UUID, host_id: UUID) -> RemovalPreview:
        try:
            async with self._pool.acquire() as db:
                async with db.transaction(isolation="repeatable_read"):
                    await db.execute("SET LOCAL statement_timeout='5s'")
                    await self._authority(db, actor_id)
                    host = await db.fetchrow(
                        "SELECT id, revision FROM site_host WHERE id=$1", host_id
                    )
                    if host is None:
                        raise _host_not_found()
                    now = datetime.now(timezone.utc)
                    live = await db.fetch(
                        _BINDING_SELECT
                        + " WHERE b.site_host_id=$1 AND b.valid_to IS NULL"
                        " ORDER BY b.at_root DESC, b.edition_segment",
                        host_id,
                    )
                    current = await self._canonical.for_actions(
                        db, (row["action_id"] for row in live), now
                    )
                    after = await self._canonical.for_actions(
                        db,
                        (row["action_id"] for row in live),
                        now,
                        exclude_host_id=host_id,
                    )
                    sources = await db.fetch(
                        "SELECT hostname FROM site_host WHERE redirect_to_host_id=$1 "
                        "ORDER BY hostname",
                        host_id,
                    )
                    return RemovalPreview(
                        host_id=host_id,
                        revision=host["revision"],
                        items=tuple(
                            RemovalPreviewItem(
                                binding_id=row["id"],
                                action_id=row["action_id"],
                                action_name=row["action_name"],
                                current_url=current.get(row["action_id"])
                                or edition_url(live_edition(row, now)),
                                new_url=after.get(row["action_id"]),
                            )
                            for row in live
                        ),
                        redirect_hosts=tuple(row["hostname"] for row in sources),
                    )
        except BUSY:
            raise _busy() from None

    async def _views(
        self,
        db: asyncpg.Connection[Any],
        host_ids: Sequence[UUID] | None,
        now: datetime,
    ) -> list[SiteHostView]:
        hosts = await db.fetch(
            """
            SELECT h.*, target.hostname AS redirect_to_hostname
            FROM site_host AS h
            LEFT JOIN site_host AS target ON target.id = h.redirect_to_host_id
            WHERE $1::uuid[] IS NULL OR h.id = ANY($1::uuid[])
            ORDER BY h.hostname
            """,
            list(host_ids) if host_ids is not None else None,
        )
        ids = [row["id"] for row in hosts]
        bindings = await db.fetch(
            _BINDING_SELECT + " WHERE b.site_host_id = ANY($1::uuid[])"
            " ORDER BY b.valid_to IS NOT NULL, b.at_root DESC,"
            " b.valid_from DESC, b.edition_segment, b.id",
            ids,
        )
        targets = await self._canonical.for_actions(
            db,
            (row["action_id"] for row in bindings if row["valid_to"] is not None),
            now,
        )
        live: dict[UUID, list[SiteBindingView]] = defaultdict(list)
        history: dict[UUID, list[SiteBindingView]] = defaultdict(list)
        for row in bindings:
            if row["valid_to"] is None:
                live[row["site_host_id"]].append(_binding_view(row, now))
            else:
                history[row["site_host_id"]].append(
                    _binding_view(row, now, targets.get(row["action_id"]))
                )
        return [
            SiteHostView(
                id=row["id"],
                hostname=row["hostname"],
                display_hostname=display_hostname(row["hostname"]),
                status=SiteHostStatus(row["status"]),
                redirect_to_host_id=row["redirect_to_host_id"],
                redirect_to_hostname=row["redirect_to_hostname"],
                verification_token=row["verification_token"],
                verified_at=row["verified_at"],
                last_checked_at=row["last_checked_at"],
                last_check_result=row["last_check_result"],
                failed_checks=row["consecutive_failures"],
                revision=row["revision"],
                created_at=row["created_at"],
                bindings=tuple(live[row["id"]]),
                history=tuple(history[row["id"]]),
            )
            for row in hosts
        ]

    # ---------- commands ----------

    async def execute(
        self,
        actor_id: UUID,
        command: SiteHostCommand,
        *,
        hostname: str | None,
        request_id: str,
    ) -> SiteHostView:
        key = f"site-host:{command.command_id}"
        command_type = f"site_host.{command.kind}.v1"
        fingerprint = command_fingerprint(command, actor_id)
        try:
            async with self._pool.acquire() as db:
                async with db.transaction():
                    await db.execute("SET LOCAL lock_timeout='3s'")
                    await db.execute("SET LOCAL statement_timeout='5s'")
                    await db.execute("SELECT pg_advisory_xact_lock($1)", SITE_HOST_LOCK)
                    await self._authority(db, actor_id)
                    receipt = await db.fetchrow(
                        "SELECT command_type,request_hash,result FROM command_receipt "
                        "WHERE idempotency_key=$1 FOR UPDATE",
                        key,
                    )
                    now = datetime.now(timezone.utc)
                    if receipt is not None:
                        if (
                            receipt["command_type"] != command_type
                            or receipt["request_hash"] != fingerprint
                        ):
                            raise Conflict(
                                "idempotency_conflict",
                                "Diese Vorgangs-ID wurde für andere Daten verwendet.",
                            )
                        host_id = UUID(json.loads(receipt["result"])["hostId"])
                        return (await self._views(db, [host_id], now))[0]
                    context = _Context(db, actor_id, request_id)
                    host_id = await self._dispatch(context, command, hostname)
                    await db.execute(
                        "INSERT INTO command_receipt(idempotency_key,command_type,"
                        "request_hash,result,completed_at) "
                        "VALUES($1,$2,$3,$4::jsonb,clock_timestamp())",
                        key,
                        command_type,
                        fingerprint,
                        json.dumps({"hostId": str(host_id)}),
                    )
                    # The role is checked again at the final authority point.
                    await self._authority(db, actor_id)
                    return (await self._views(db, [host_id], now))[0]
        except asyncpg.UniqueViolationError as error:
            raise _unique_conflict(error) from None
        except BUSY:
            raise _busy() from None

    async def _dispatch(
        self, context: _Context, command: SiteHostCommand, hostname: str | None
    ) -> UUID:
        if isinstance(command, AddSiteHost):
            assert hostname is not None
            return await self._add(context, hostname)
        host = await context.host(command.host_id, command.revision)
        if isinstance(command, SetRedirectHost):
            await self._set_redirect(context, host, command.target_host_id)
        elif isinstance(command, BindEdition):
            await self._bind(
                context, host, command.action_id, command.segment, command.at_root
            )
        elif isinstance(command, ChangeEditionSegment):
            await self._change_segment(
                context, host, command.binding_id, command.segment
            )
        elif isinstance(command, MoveRootToEdition):
            await self._move_root(context, host, command.action_id, command.segment)
        elif isinstance(command, SetPrimaryEdition):
            await self._set_primary(context, host, command.binding_id)
        elif isinstance(command, UnbindEdition):
            await self._unbind(
                context, host, command.binding_id, command.confirm_root_removal
            )
        elif isinstance(command, RemoveSiteHost):
            await self._remove(context, host)
        else:  # pragma: no cover - the union is closed
            raise TypeError(type(command).__name__)
        await context.db.execute(
            "UPDATE site_host SET revision=revision+1, updated_at=clock_timestamp() "
            "WHERE id=$1",
            host["id"],
        )
        return UUID(str(host["id"]))

    async def _add(self, context: _Context, hostname: str) -> UUID:
        db = context.db
        existing = await db.fetchrow(
            "SELECT * FROM site_host WHERE hostname=$1 FOR UPDATE", hostname
        )
        token = secrets.token_urlsafe(32)
        if existing is not None:
            live = await db.fetchval(
                "SELECT count(*) FROM site_binding WHERE site_host_id=$1 AND valid_to IS NULL",
                existing["id"],
            )
            if existing["status"] != SiteHostStatus.DISABLED or live:
                raise Conflict(
                    "site_host_exists", "Dieser Host ist bereits eingetragen."
                )
            # Re-add after removal (§7.7.6): a new token, a new check.
            await db.execute(
                """
                UPDATE site_host
                SET status='pending', verification_token=$2, verified_at=NULL,
                    last_checked_at=NULL, last_check_result=NULL,
                    consecutive_failures=0, failing_since=NULL, tls_approved_at=NULL,
                    redirect_to_host_id=NULL, revision=revision+1,
                    updated_at=clock_timestamp()
                WHERE id=$1
                """,
                existing["id"],
                token,
            )
            await context.audit(
                "site_host.readded", existing["id"], None, {"hostname": hostname}
            )
            return UUID(str(existing["id"]))
        host_id = uuid4()
        await db.execute(
            "INSERT INTO site_host(id,hostname,verification_token,created_by) "
            "VALUES($1,$2,$3,$4)",
            host_id,
            hostname,
            token,
            context.actor_id,
        )
        await context.audit("site_host.added", host_id, None, {"hostname": hostname})
        return host_id

    async def _set_redirect(
        self, context: _Context, host: asyncpg.Record, target_id: UUID | None
    ) -> None:
        db = context.db
        _require_usable(host)
        if target_id is not None:
            target = await db.fetchrow(
                "SELECT * FROM site_host WHERE id=$1 FOR UPDATE", target_id
            )
            if target is None:
                raise _host_not_found()
            if target["status"] == SiteHostStatus.DISABLED:
                raise Conflict(
                    "site_host_redirect_target_disabled",
                    "Das Ziel ist abgeschaltet. Bitte zuerst neu eintragen.",
                )
            if target["redirect_to_host_id"] is not None:
                raise Conflict(
                    "site_host_redirect_chain",
                    "Das Ziel leitet selbst weiter. Bitte direkt auf den Kampagnen-Host zeigen.",
                )
            if await _live_count(db, host["id"]):
                raise Conflict(
                    "site_host_has_editions",
                    "Ein Host mit Ausgaben kann nicht weiterleiten. Bitte die Ausgaben zuerst lösen.",
                )
            sources = await db.fetchval(
                "SELECT count(*) FROM site_host WHERE redirect_to_host_id=$1",
                host["id"],
            )
            if sources:
                raise Conflict(
                    "site_host_is_redirect_target",
                    "Andere Hosts leiten auf diesen Host weiter; er kann nicht selbst weiterleiten.",
                )
        await db.execute(
            "UPDATE site_host SET redirect_to_host_id=$2 WHERE id=$1",
            host["id"],
            target_id,
        )
        await context.audit(
            "site_host.redirect_changed",
            host["id"],
            None,
            {
                "previousTarget": _text(host["redirect_to_host_id"]),
                "newTarget": _text(target_id),
            },
        )

    async def _bind(
        self,
        context: _Context,
        host: asyncpg.Record,
        action_id: UUID,
        segment: str | None,
        at_root: bool,
    ) -> UUID:
        db = context.db
        _require_usable(host)
        if host["redirect_to_host_id"] is not None:
            raise Conflict(
                "site_host_is_redirect",
                "Ein Weiterleitungs-Host hat keine Ausgaben.",
            )
        action = await db.fetchrow(
            "SELECT id, archive_slug, starts_on, publication_starts_at "
            "FROM charity_action WHERE id=$1 FOR SHARE",
            action_id,
        )
        if action is None:
            raise ResourceNotFound(
                "site_edition_action_not_found", "Aktion nicht gefunden."
            )
        if await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM site_binding WHERE site_host_id=$1 "
            "AND action_id=$2 AND valid_to IS NULL)",
            host["id"],
            action_id,
        ):
            raise Conflict(
                "site_edition_action_bound",
                "Diese Aktion ist auf diesem Host bereits eine Ausgabe.",
            )
        taken = [
            row["edition_segment"]
            for row in await db.fetch(
                "SELECT edition_segment FROM site_binding WHERE site_host_id=$1 "
                "AND valid_to IS NULL",
                host["id"],
            )
        ]
        if segment is None:
            segment = default_edition_segment(
                publication_starts_at=action["publication_starts_at"],
                starts_on=action["starts_on"],
                archive_slug=action["archive_slug"],
                taken=taken,
            )
        elif segment in taken:
            raise Conflict(
                "site_edition_segment_taken",
                "Dieses Pfadsegment gehört auf diesem Host schon zu einer anderen Ausgabe.",
            )
        if at_root and await _root_binding(db, host["id"]) is not None:
            raise Conflict(
                "site_edition_root_taken",
                "Eine andere Ausgabe hält die Wurzel. Bitte „Domain an Folgeaktion übergeben“ nutzen.",
            )
        primary = not await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM site_binding WHERE action_id=$1 "
            "AND is_primary AND valid_to IS NULL)",
            action_id,
        )
        binding_id = uuid4()
        await db.execute(
            "INSERT INTO site_binding(id,site_host_id,action_id,edition_segment,at_root,"
            "is_primary,valid_from,created_by) VALUES($1,$2,$3,$4,$5,$6,clock_timestamp(),$7)",
            binding_id,
            host["id"],
            action_id,
            segment,
            at_root,
            primary,
            context.actor_id,
        )
        await context.audit(
            "site_edition.bound",
            host["id"],
            action_id,
            {
                "bindingId": str(binding_id),
                "segment": segment,
                "atRoot": at_root,
                "isPrimary": primary,
            },
        )
        return binding_id

    async def _change_segment(
        self, context: _Context, host: asyncpg.Record, binding_id: UUID, segment: str
    ) -> None:
        db = context.db
        _require_usable(host)
        binding = await _live_binding(db, host["id"], binding_id)
        if binding["edition_segment"] == segment:
            return
        if await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM site_binding WHERE site_host_id=$1 "
            "AND edition_segment=$2 AND valid_to IS NULL)",
            host["id"],
            segment,
        ):
            raise Conflict(
                "site_edition_segment_taken",
                "Dieses Pfadsegment gehört auf diesem Host schon zu einer anderen Ausgabe.",
            )
        # Retire first: the partial unique indexes see one live row at a time.
        await _retire(db, binding_id, "segment_changed")
        new_id = uuid4()
        await db.execute(
            "INSERT INTO site_binding(id,site_host_id,action_id,edition_segment,at_root,"
            "is_primary,valid_from,created_by) VALUES($1,$2,$3,$4,$5,$6,clock_timestamp(),$7)",
            new_id,
            host["id"],
            binding["action_id"],
            segment,
            binding["at_root"],
            binding["is_primary"],
            context.actor_id,
        )
        await context.audit(
            "site_edition.segment_changed",
            host["id"],
            binding["action_id"],
            {
                "previousBindingId": str(binding_id),
                "bindingId": str(new_id),
                "previousSegment": binding["edition_segment"],
                "segment": segment,
            },
        )

    async def _move_root(
        self,
        context: _Context,
        host: asyncpg.Record,
        action_id: UUID,
        segment: str | None,
    ) -> None:
        db = context.db
        _require_usable(host)
        if host["redirect_to_host_id"] is not None:
            raise Conflict(
                "site_host_is_redirect", "Ein Weiterleitungs-Host hat keine Ausgaben."
            )
        target = await db.fetchrow(
            "SELECT * FROM site_binding WHERE site_host_id=$1 AND action_id=$2 "
            "AND valid_to IS NULL FOR UPDATE",
            host["id"],
            action_id,
        )
        if (
            target is not None
            and segment is not None
            and segment != target["edition_segment"]
        ):
            raise Conflict(
                "site_edition_segment_mismatch",
                "Die Aktion ist bereits gebunden; das Pfadsegment bitte separat ändern.",
            )
        if target is not None and target["at_root"]:
            return
        status = await db.fetchval(
            "SELECT status FROM charity_action WHERE id=$1 FOR SHARE", action_id
        )
        if status is None:
            raise ResourceNotFound(
                "site_edition_action_not_found", "Aktion nicht gefunden."
            )
        if status in {"completed", "archived"}:
            raise Conflict(
                "site_edition_follow_up_ended",
                "Die Folgeaktion ist bereits beendet.",
            )
        previous = await _root_binding(db, host["id"])
        if previous is not None:
            await db.execute(
                "UPDATE site_binding SET at_root=false, revision=revision+1, "
                "updated_at=clock_timestamp() WHERE id=$1",
                previous["id"],
            )
            await context.audit(
                "site_edition.root_released",
                host["id"],
                previous["action_id"],
                {
                    "bindingId": str(previous["id"]),
                    "segment": previous["edition_segment"],
                },
            )
        if target is None:
            await self._bind(context, host, action_id, segment, True)
            return
        await db.execute(
            "UPDATE site_binding SET at_root=true, revision=revision+1, "
            "updated_at=clock_timestamp() WHERE id=$1",
            target["id"],
        )
        await context.audit(
            "site_edition.root_taken",
            host["id"],
            action_id,
            {"bindingId": str(target["id"]), "segment": target["edition_segment"]},
        )

    async def _set_primary(
        self, context: _Context, host: asyncpg.Record, binding_id: UUID
    ) -> None:
        db = context.db
        binding = await _live_binding(db, host["id"], binding_id)
        if binding["is_primary"]:
            return
        previous = await db.fetchrow(
            "SELECT id, site_host_id FROM site_binding WHERE action_id=$1 AND is_primary "
            "AND valid_to IS NULL FOR UPDATE",
            binding["action_id"],
        )
        if previous is not None:
            await db.execute(
                "UPDATE site_binding SET is_primary=false, revision=revision+1, "
                "updated_at=clock_timestamp() WHERE id=$1",
                previous["id"],
            )
        await db.execute(
            "UPDATE site_binding SET is_primary=true, revision=revision+1, "
            "updated_at=clock_timestamp() WHERE id=$1",
            binding_id,
        )
        await context.audit(
            "site_edition.primary_changed",
            host["id"],
            binding["action_id"],
            {
                "bindingId": str(binding_id),
                "previousBindingId": _text(previous["id"] if previous else None),
            },
        )

    async def _unbind(
        self,
        context: _Context,
        host: asyncpg.Record,
        binding_id: UUID,
        confirm_root_removal: bool,
    ) -> None:
        db = context.db
        binding = await _live_binding(db, host["id"], binding_id)
        if (
            binding["at_root"]
            and await _live_count(db, host["id"]) == 1
            and not confirm_root_removal
        ):
            raise Conflict(
                "site_edition_root_only",
                "Das ist die einzige Ausgabe dieses Hosts; danach zeigt „/“ eine "
                "Fehlerseite. Bitte bestätigen.",
            )
        await _retire(db, binding_id, "unbound")
        await _promote_primary(db, binding)
        await context.audit(
            "site_edition.unbound",
            host["id"],
            binding["action_id"],
            {"bindingId": str(binding_id), "segment": binding["edition_segment"]},
        )

    async def _remove(self, context: _Context, host: asyncpg.Record) -> None:
        db = context.db
        if host["status"] == SiteHostStatus.DISABLED and not await _live_count(
            db, host["id"]
        ):
            raise Conflict("site_host_removed", "Dieser Host ist bereits entfernt.")
        sources = await db.fetch(
            "SELECT hostname FROM site_host WHERE redirect_to_host_id=$1 ORDER BY hostname",
            host["id"],
        )
        if sources:
            raise Conflict(
                "site_host_is_redirect_target",
                "Diese Hosts leiten noch hierher weiter: "
                + ", ".join(row["hostname"] for row in sources)
                + ". Bitte sie zuerst entfernen oder umstellen.",
            )
        bindings = await db.fetch(
            "SELECT * FROM site_binding WHERE site_host_id=$1 AND valid_to IS NULL "
            "ORDER BY id FOR UPDATE",
            host["id"],
        )
        for binding in bindings:
            await _retire(db, binding["id"], "host_removed")
            await _promote_primary(db, binding)
        await db.execute(
            "UPDATE site_host SET status='disabled', redirect_to_host_id=NULL WHERE id=$1",
            host["id"],
        )
        await context.audit(
            "site_host.removed",
            host["id"],
            None,
            {
                "hostname": host["hostname"],
                "retiredBindings": [str(row["id"]) for row in bindings],
            },
        )

    @staticmethod
    async def _authority(db: asyncpg.Connection[Any], actor: UUID) -> None:
        status = await db.fetchval(
            "SELECT status FROM user_account WHERE id=$1 FOR SHARE", actor
        )
        roles = await db.fetch(
            "SELECT role FROM user_global_role WHERE user_id=$1 FOR SHARE", actor
        )
        if status != "active" or not any(
            row["role"] == "system_admin" for row in roles
        ):
            raise PermissionDenied(
                "system_admin_required",
                "Domains verwalten ist ausschließlich für System-Admins erlaubt.",
            )


@dataclass(frozen=True, slots=True)
class _Context:
    db: asyncpg.Connection[Any]
    actor_id: UUID
    request_id: str

    async def host(self, host_id: UUID, revision: int) -> asyncpg.Record:
        row = await self.db.fetchrow(
            "SELECT * FROM site_host WHERE id=$1 FOR UPDATE", host_id
        )
        if row is None:
            raise _host_not_found()
        if row["revision"] != revision:
            raise Conflict(
                "site_host_revision_conflict",
                "Der Host wurde inzwischen geändert. Bitte neu laden.",
            )
        return row

    async def audit(
        self,
        event_type: str,
        host_id: UUID,
        action_id: UUID | None,
        payload: dict[str, Any],
    ) -> None:
        await self.db.execute(
            "INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,"
            "entity_id,request_id,payload) VALUES($1,$2,$3,$4,'site_host',$5,$6,$7::jsonb)",
            uuid4(),
            action_id,
            self.actor_id,
            event_type,
            host_id,
            self.request_id,
            json.dumps(payload),
        )


def _text(value: object | None) -> str | None:
    return None if value is None else str(value)


def _require_usable(host: asyncpg.Record) -> None:
    if host["status"] == SiteHostStatus.DISABLED:
        raise Conflict(
            "site_host_disabled",
            "Dieser Host ist abgeschaltet. Bitte erneut prüfen oder neu eintragen.",
        )


async def _live_count(db: asyncpg.Connection[Any], host_id: UUID) -> int:
    return int(
        await db.fetchval(
            "SELECT count(*) FROM site_binding WHERE site_host_id=$1 AND valid_to IS NULL",
            host_id,
        )
    )


async def _root_binding(
    db: asyncpg.Connection[Any], host_id: UUID
) -> asyncpg.Record | None:
    return await db.fetchrow(
        "SELECT * FROM site_binding WHERE site_host_id=$1 AND at_root "
        "AND valid_to IS NULL FOR UPDATE",
        host_id,
    )


async def _live_binding(
    db: asyncpg.Connection[Any], host_id: UUID, binding_id: UUID
) -> asyncpg.Record:
    row = await db.fetchrow(
        "SELECT * FROM site_binding WHERE id=$1 AND site_host_id=$2 "
        "AND valid_to IS NULL FOR UPDATE",
        binding_id,
        host_id,
    )
    if row is None:
        raise ResourceNotFound(
            "site_edition_not_found", "Diese Ausgabe ist nicht (mehr) gebunden."
        )
    return row


async def _retire(db: asyncpg.Connection[Any], binding_id: UUID, reason: str) -> None:
    await db.execute(
        "UPDATE site_binding SET valid_to=clock_timestamp(), ended_reason=$2, "
        "at_root=false, is_primary=false, revision=revision+1, "
        "updated_at=clock_timestamp() WHERE id=$1",
        binding_id,
        reason,
    )


async def _promote_primary(
    db: asyncpg.Connection[Any], retired: asyncpg.Record
) -> None:
    """The oldest remaining live binding becomes canonical (§7.7.5)."""
    if not retired["is_primary"]:
        return
    await db.execute(
        """
        UPDATE site_binding SET is_primary=true, revision=revision+1,
               updated_at=clock_timestamp()
        WHERE id = (
            SELECT id FROM site_binding
            WHERE action_id=$1 AND valid_to IS NULL
            ORDER BY valid_from, id LIMIT 1
        )
        """,
        retired["action_id"],
    )


def _host_not_found() -> ResourceNotFound:
    return ResourceNotFound("site_host_not_found", "Host nicht gefunden.")


def _busy() -> Conflict:
    return Conflict(
        "site_host_busy",
        "Die Domain-Verwaltung ist beschäftigt. Bitte denselben Vorgang erneut versuchen.",
    )


def _unique_conflict(error: asyncpg.UniqueViolationError) -> Conflict:
    constraint = getattr(error, "constraint_name", "") or ""
    messages = {
        "uq_site_host_hostname": (
            "site_host_exists",
            "Dieser Host ist bereits eingetragen.",
        ),
        "uq_site_binding_root": (
            "site_edition_root_taken",
            "Eine andere Ausgabe hält bereits die Wurzel dieses Hosts.",
        ),
        "uq_site_binding_segment": (
            "site_edition_segment_taken",
            "Dieses Pfadsegment gehört auf diesem Host schon zu einer anderen Ausgabe.",
        ),
        "uq_site_binding_host_action": (
            "site_edition_action_bound",
            "Diese Aktion ist auf diesem Host bereits eine Ausgabe.",
        ),
        "uq_site_binding_primary": (
            "site_edition_primary_conflict",
            "Die Aktion hat bereits eine Hauptadresse.",
        ),
    }
    code, message = messages.get(
        constraint, ("site_host_conflict", "Dieser Vorgang widerspricht einem anderen.")
    )
    return Conflict(code, message)

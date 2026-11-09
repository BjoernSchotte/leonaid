"""Delivery tours against real PostgreSQL (specs/krapfentaxi-touren).

Proves the feature flag gate, base and driver order writes with their
revision and no-op rules, the driver's scope, tour membership changes
(assignment, reassignment, cancellation, window change), the read audit of
"Meine Tour", discarding a driver order, and the driver's "Nicht
angetroffen" through window closure and reopening (Rulings 1, 5, 6).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.feature_flags.openfeature import (
    LeonAidFeatureProvider,
    OpenFeatureBooleanEvaluator,
)
from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import (
    AsyncpgDeliveryRepository,
    write_order_delivery,
)
from leonaid.adapters.postgres.delivery_board import AsyncpgDeliveryBoardRepository
from leonaid.adapters.postgres.delivery_tours import AsyncpgDeliveryTourRepository
from leonaid.adapters.postgres.feature_flags import AsyncpgFeatureFlagRepository
from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.delivery_board import DeliveryBoardService
from leonaid.application.delivery_tours import DeliveryTourService
from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.delivery import DeliveryContactSnapshot, DeliveryWindow
from leonaid.domain.delivery_board import DeliveryDrop, DropState
from leonaid.domain.delivery_tours import DayTours, DriverTour, MyTour
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.modules.tasks.delivery_follow_up import TaskDeliveryFollowUp
from tools.delivery.board import _expect, _principal, _user
from tools.delivery.http_configuration import http_app

REQUEST = "tours-proof"


def _ids(tour: DriverTour) -> list[list[UUID]]:
    """Commitment ids per window, in effective order."""

    return [[stop.drop.commitment_id for stop in item.stops] for item in tour.windows]


def _flat(tour: DriverTour) -> list[UUID]:
    return [commitment_id for ids in _ids(tour) for commitment_id in ids]


class _Fixture:
    """Services, people, windows and orders shared by the sections."""

    def __init__(self, pool: asyncpg.Pool, action_id: UUID, admin_id: UUID) -> None:
        self.pool = pool
        self.action_id = action_id
        self.admin_id = admin_id
        self.now = datetime.now(timezone.utc)
        self.orders = AsyncpgCommitmentRepository(pool)
        self.flags = FeatureFlagService(
            AsyncpgFeatureFlagRepository(pool),
            OpenFeatureBooleanEvaluator(LeonAidFeatureProvider()),
        )
        self.tours = DeliveryTourService(
            AsyncpgDeliveryTourRepository(pool), self.flags
        )
        self.board = DeliveryBoardService(
            AsyncpgDeliveryBoardRepository(pool, lambda _c: TaskDeliveryFollowUp()),
            flags=self.flags,
            follow_up_tasks=True,
        )
        self.offering_id: UUID | None = None
        self.admin = _principal(admin_id, action_id, ActionRole.CHARITY_ADMIN)
        # Own windows: earlier proofs close or retire the action's first ones.
        # Days no other delivery proof uses.
        self.day, self.other_day = date(2037, 12, 25), date(2037, 12, 26)
        self.first = DeliveryWindow(uuid4(), action_id, self.day, time(8), time(10))
        self.second = DeliveryWindow(uuid4(), action_id, self.day, time(10), time(12))
        self.third = DeliveryWindow(
            uuid4(), action_id, self.other_day, time(8), time(10)
        )

    async def setup(self) -> None:
        schedules = AsyncpgDeliveryRepository(self.pool)
        configuration = await schedules.get(self.action_id)
        await schedules.save(
            replace(
                configuration,
                windows=(*configuration.windows, self.first, self.second, self.third),
            )
        )
        self.anna_id = await self.driver("Tourfahrerin Anna")
        self.ben_id = await self.driver("Tourfahrer Ben")
        self.anna = _principal(self.anna_id, self.action_id, ActionRole.DRIVER)
        self.ben = _principal(self.ben_id, self.action_id, ActionRole.DRIVER)
        # A driver of another action: no access to this action's tour.
        self.foreign = _principal(
            await _user(self.pool, "Fremdfahrer"), uuid4(), ActionRole.DRIVER
        )
        self.a1 = await self.order("Tour A1", self.first.id)
        self.a2 = await self.order("Tour A2", self.first.id)
        self.a3 = await self.order("Tour A3", self.first.id)
        self.a4 = await self.order("Tour A4", self.second.id)
        self.b1 = await self.order("Tour B1", self.first.id)
        self.unassigned = await self.order("Tour Offen", self.first.id)
        self.later = await self.order("Tour Folgetag", self.third.id)
        await self.assign(self.anna_id, self.a1, self.a2, self.a3, self.a4, self.later)
        await self.assign(self.ben_id, self.b1)

    async def day_tours(
        self, actor: IdentityPrincipal | None = None, on: date | None = None
    ) -> DayTours:
        return await self.tours.day_tours(
            actor or self.admin,
            self.action_id,
            day=on or self.day,
            viewed_at=datetime.now(timezone.utc),
        )

    async def my_tour(
        self, actor: IdentityPrincipal | None = None, on: date | None = None
    ) -> MyTour:
        return await self.tours.my_tour(
            actor or self.anna,
            self.action_id,
            day=on,
            viewed_at=datetime.now(timezone.utc),
        )

    async def own_tour(self, on: date | None = None) -> DriverTour:
        tour = (await self.my_tour(on=on or self.day)).tour
        assert tour is not None
        return tour

    async def tour_of(self, driver_user_id: UUID) -> DriverTour:
        found = [
            tour
            for tour in (await self.day_tours()).tours
            if tour.driver_user_id == driver_user_id
        ]
        assert len(found) == 1, found
        return found[0]

    async def save_driver(
        self,
        ids: tuple[UUID, ...],
        revision: str,
        *,
        on: date | None = None,
        actor: IdentityPrincipal | None = None,
        at: datetime | None = None,
    ) -> DriverTour:
        return await self.tours.save_driver_order(
            actor or self.anna,
            self.action_id,
            day=on or self.day,
            ordered_ids=ids,
            expected_revision=revision,
            request_id=REQUEST,
            occurred_at=at or self.now,
        )

    async def save_base(
        self,
        ids: tuple[UUID, ...],
        revision: str,
        *,
        on: date | None = None,
        actor: IdentityPrincipal | None = None,
    ) -> DriverTour:
        return await self.tours.save_base_order(
            actor or self.admin,
            self.action_id,
            self.anna_id,
            day=on or self.day,
            ordered_ids=ids,
            expected_revision=revision,
            request_id=REQUEST,
            occurred_at=self.now,
        )

    async def discard(self, actor: IdentityPrincipal | None = None) -> DriverTour:
        return await self.tours.discard_driver_order(
            actor or self.admin,
            self.action_id,
            self.anna_id,
            day=self.day,
            request_id=REQUEST,
            occurred_at=self.now,
        )

    async def order(self, name: str, window_id: UUID) -> UUID:
        if self.offering_id is None:
            self.offering_id = await self.pool.fetchval(
                "SELECT id FROM offering WHERE action_id=$1 LIMIT 1", self.action_id
            )
        assert self.offering_id is not None
        draft = CommitmentDraft(
            BuyerSnapshot(
                CommitmentPartyKind.PERSON,
                uuid4(),
                name,
                f"{name.lower().replace(' ', '.')}@example.invalid",
            ),
            InvoiceRecipientSnapshot(name, "Rechnungsweg 1", "12345", "Test"),
            (CommitmentLineDraft(self.offering_id, 1, OfferingUnit.BOX, 3600),),
            DeliveryRecipientSnapshot(name, "Tourweg 3", "12345", "Test"),
            delivery_window_id=window_id,
            delivery_contact=DeliveryContactSnapshot("Tür", "+49 30 456"),
        )
        status = CommitmentStatus.REVIEW_READY
        created = await self.orders.create(
            action_id=self.action_id,
            actor_user_id=self.admin_id,
            source=CommitmentSource.ADMIN,
            status=status,
            draft=draft,
            idempotency_key=f"tours:{uuid4()}",
            request_hash=draft.fingerprint(
                action_id=self.action_id, source=CommitmentSource.ADMIN, status=status
            ),
            request_id=REQUEST,
            occurred_at=self.now,
        )
        return created.id

    async def driver(self, name: str) -> UUID:
        user_id = await _user(self.pool, name)
        await self.pool.execute(
            "INSERT INTO action_membership(id,action_id,user_id,role)"
            " VALUES ($1,$2,$3,'driver')",
            uuid4(),
            self.action_id,
            user_id,
        )
        return user_id

    async def assign(self, driver_user_id: UUID | None, *ids: UUID) -> None:
        admin = _principal(self.admin_id, self.action_id, ActionRole.CHARITY_ADMIN)
        await self.board.assign_driver(
            admin,
            self.action_id,
            commitment_ids=ids,
            driver_user_id=driver_user_id,
            request_id=REQUEST,
            occurred_at=self.now,
        )

    async def positions(self, commitment_id: UUID) -> asyncpg.Record:
        row = await self.pool.fetchrow(
            "SELECT base_position, driver_position, driver_ordered_at"
            " FROM commitment_delivery WHERE commitment_id=$1",
            commitment_id,
        )
        assert row is not None
        return row

    async def events(self, event_type: str) -> list[dict[str, object]]:
        rows = await self.pool.fetch(
            "SELECT payload FROM audit_event WHERE action_id=$1 AND event_type=$2"
            " AND request_id=$3 ORDER BY occurred_at, id",
            self.action_id,
            event_type,
            REQUEST,
        )
        return [json.loads(row["payload"]) for row in rows]


async def prove_tours(pool: asyncpg.Pool, action_id: UUID, admin_id: UUID) -> None:
    fx = _Fixture(pool, action_id, admin_id)
    await fx.setup()

    # flag off: day_tours and my_tour raise ResourceNotFound feature_flag_disabled
    await pool.execute(
        "UPDATE feature_flag SET enabled=false, revision=revision+1"
        " WHERE key='delivery.tours'"
    )
    await _expect(fx.day_tours(), ResourceNotFound, "feature_flag_disabled")
    await _expect(fx.my_tour(), ResourceNotFound, "feature_flag_disabled")
    await _expect(fx.save_driver((), "x"), ResourceNotFound, "feature_flag_disabled")
    await _expect(
        fx.save_base((fx.a1,), "x"), ResourceNotFound, "feature_flag_disabled"
    )
    await _expect(fx.discard(), ResourceNotFound, "feature_flag_disabled")
    await pool.execute(
        "UPDATE feature_flag SET enabled=true, revision=revision+1"
        " WHERE key='delivery.tours'"
    )
    try:
        await prove_tour_http(fx)
        await _prove_orders(fx)
        await prove_tour_membership_changes(fx)
        await _prove_access_and_audit(fx)
        await _prove_discard(fx)
        await prove_driver_missed(fx)
    finally:
        await pool.execute(
            "UPDATE feature_flag SET enabled=false, revision=revision+1"
            " WHERE key='delivery.tours'"
        )
    print(
        "TOURS PASS: flag gate, base order with no-op and revision conflict,"
        " driver order beside the base order, driver scope, foreign driver"
        " refused, one read audit per window and day, discard and empty driver"
        " write reset, five HTTP operations (roles, flag, no-store)"
    )


async def prove_tour_http(fx: _Fixture) -> None:
    """The five tour operations over ASGI: roles, flag gate, no-store."""
    app, identity = http_app(fx.admin)
    app.state.delivery_tour_service = fx.tours
    base = f"/api/v1/actions/{fx.action_id}"
    day = fx.day.isoformat()
    manager_paths = {
        "get": f"{base}/delivery-board/tours?day={day}",
        "put": f"{base}/delivery-board/tours/{fx.anna_id}/order",
        "delete": f"{base}/delivery-board/tours/{fx.anna_id}/driver-order?day={day}",
    }
    driver_paths = {"get": f"{base}/my-tour?day={day}", "put": f"{base}/my-tour/order"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        def order_body(tour: dict[str, object]) -> dict[str, object]:
            ids = [
                stop["drop"]["commitmentId"]
                for window in tour["windows"]  # type: ignore[attr-defined]
                for stop in window["stops"]
            ]
            return {
                "day": day,
                "expectedRevision": tour["revision"],
                "commitmentIds": ids,
            }

        async def call(name: str, method: str, path: str, body: object = None):  # type: ignore[no-untyped-def]
            response = await client.request(method, path, json=body)
            assert response.headers["cache-control"] == "private, no-store" or (
                response.status_code != 200
            ), name
            return response

        # Manager: the day overview, then base order and discard.
        response = await call("day", "GET", manager_paths["get"])
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        overview = response.json()
        assert overview["day"] == day and overview["unassigned"]
        anna = next(
            t for t in overview["tours"] if t["driverUserId"] == str(fx.anna_id)
        )
        body = order_body(anna)
        response = await call("base", "PUT", manager_paths["put"], body)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["driverUserId"] == str(fx.anna_id)
        response = await call("discard", "DELETE", manager_paths["delete"])
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["driverOrderedAt"] is None
        # Strict request bodies: unknown fields and a missing day are refused.
        assert (
            await client.put(manager_paths["put"], json={**body, "extra": 1})
        ).status_code == 422
        assert (
            await client.delete(
                f"{base}/delivery-board/tours/{fx.anna_id}/driver-order"
            )
        ).status_code == 422
        # A driver may not use the manager operations.
        identity.current = fx.anna
        assert (await client.get(manager_paths["get"])).status_code == 403
        assert (await client.put(manager_paths["put"], json=body)).status_code == 403
        assert (await client.delete(manager_paths["delete"])).status_code == 403

        # Driver: own tour, own order, empty list resets.
        response = await call("mine", "GET", driver_paths["get"])
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        mine = response.json()
        assert mine["tour"]["driverUserId"] == str(fx.anna_id)
        own = order_body(mine["tour"])
        response = await call("own", "PUT", driver_paths["put"], own)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        saved = response.json()
        assert saved["driverOrderedAt"] is not None
        response = await call(
            "reset",
            "PUT",
            driver_paths["put"],
            {**own, "expectedRevision": saved["revision"], "commitmentIds": []},
        )
        assert response.status_code == 200, response.text
        assert response.json()["driverOrderedAt"] is None
        # A driver of another action and a manager (no driver role) are refused.
        for outsider in (fx.foreign, fx.admin):
            identity.current = outsider
            assert (await client.get(driver_paths["get"])).status_code == 403
            assert (await client.put(driver_paths["put"], json=own)).status_code == 403
        identity.current = None
        assert (await client.get(driver_paths["get"])).status_code == 401

        # Flag off: every operation answers 404 feature_flag_disabled.
        await fx.pool.execute(
            "UPDATE feature_flag SET enabled=false, revision=revision+1"
            " WHERE key='delivery.tours'"
        )
        try:
            for actor, calls in (
                (
                    fx.admin,
                    (
                        ("GET", manager_paths["get"], None),
                        ("PUT", manager_paths["put"], body),
                        ("DELETE", manager_paths["delete"], None),
                    ),
                ),
                (
                    fx.anna,
                    (
                        ("GET", driver_paths["get"], None),
                        ("PUT", driver_paths["put"], own),
                    ),
                ),
            ):
                identity.current = actor
                for method, path, payload in calls:
                    response = await client.request(method, path, json=payload)
                    assert response.status_code == 404, (method, path, response.text)
                    assert response.json() == {"code": "feature_flag_disabled"}
        finally:
            await fx.pool.execute(
                "UPDATE feature_flag SET enabled=true, revision=revision+1"
                " WHERE key='delivery.tours'"
            )


async def _prove_orders(fx: _Fixture) -> None:
    a1, a2, a3, a4, b1 = fx.a1, fx.a2, fx.a3, fx.a4, fx.b1

    # Manager view: unassigned stops by window, one tour per driver.
    overview = await fx.day_tours()
    assert overview.day == fx.day and fx.other_day in overview.days
    assert fx.unassigned in {
        stop.drop.commitment_id for item in overview.unassigned for stop in item.stops
    }
    assert {fx.anna_id, fx.ben_id} <= {tour.driver_user_id for tour in overview.tours}
    assert {fx.anna_id, fx.ben_id} <= {driver.user_id for driver in overview.drivers}
    await _expect(
        fx.day_tours(fx.anna), PermissionDenied, "delivery_management_required"
    )

    # manager saves base order; repeat with stale revision but same order is a no-op
    # The HTTP section saved Anna's order as it stood (by assignment time and
    # random ids); clear it so the order below always differs from the start.
    await fx.pool.execute(
        "UPDATE commitment_delivery SET base_position = NULL, driver_position = NULL,"
        " driver_ordered_at = NULL WHERE driver_user_id = $1",
        fx.anna_id,
    )
    start = await fx.tour_of(fx.anna_id)
    assert sorted(_flat(start)) == sorted([a1, a2, a3, a4])
    assert [item.window_id for item in start.windows] == [fx.first.id, fx.second.id]
    await _expect(
        fx.save_base((a3, a1, a4, a2), start.revision, actor=fx.anna),
        PermissionDenied,
        "delivery_management_required",
    )
    # Interleaved windows: only the order inside each window counts.
    planned = await fx.save_base((a3, a1, a4, a2), start.revision)
    assert _ids(planned) == [[a3, a1, a2], [a4]], _ids(planned)
    assert [stop.base_rank for stop in planned.windows[0].stops] == [1, 2, 3]
    assert planned.revision != start.revision
    assert planned.driver_ordered_at is None
    assert (await fx.positions(a2))["base_position"] == 3
    saved_events = await fx.events("delivery.tour_order_saved")
    assert saved_events == [
        {
            "driverUserId": str(fx.anna_id),
            "day": fx.day.isoformat(),
            "stopCount": 4,
            "kind": "base",
        }
    ], saved_events
    repeated = await fx.save_base((a3, a1, a2, a4), start.revision)
    assert repeated.revision == planned.revision
    assert len(await fx.events("delivery.tour_order_saved")) == 1

    # stale revision with a different order: tour_revision_conflict
    await _expect(
        fx.save_base((a1, a3, a2, a4), start.revision),
        Conflict,
        "tour_revision_conflict",
    )

    # driver saves own order; base ranks unchanged; driver_ordered_at set
    own = await fx.my_tour(on=fx.day)
    assert own.tour is not None and own.days == (fx.day, fx.other_day), own.days
    assert own.tour.revision == planned.revision
    assert _ids(own.tour) == [[a3, a1, a2], [a4]]
    # P3: the driver's drops carry no order status or who changed what.
    assert all(
        stop.drop.order_status is None and stop.drop.driver_name is None
        for item in own.tour.windows
        for stop in item.stops
    )
    ordered_at = fx.now + timedelta(minutes=5)
    mine = await fx.save_driver((a2, a1, a3, a4), own.tour.revision, at=ordered_at)
    assert _ids(mine) == [[a2, a1, a3], [a4]]
    assert mine.driver_ordered_at == ordered_at
    by_id = {
        stop.drop.commitment_id: stop for item in mine.windows for stop in item.stops
    }
    assert [by_id[i].base_rank for i in (a3, a1, a2)] == [1, 2, 3]
    assert [by_id[i].driver_rank for i in (a2, a1, a3)] == [1, 2, 3]
    assert all(stop.drop.order_status is None for stop in by_id.values())
    row = await fx.positions(a3)
    assert row["base_position"] == 1 and row["driver_position"] == 3
    assert row["driver_ordered_at"] == ordered_at
    assert (await fx.events("delivery.tour_order_saved"))[-1]["kind"] == "driver"
    # The manager sees the driver's order and when it was made.
    seen = await fx.tour_of(fx.anna_id)
    assert _ids(seen) == [[a2, a1, a3], [a4]] and seen.driver_ordered_at == ordered_at

    # driver order with another driver's commitment: tour_order_stale
    for wrong in ((a2, a1, b1, a4), (a2, a1, a3, a4, b1), (a2, a1, a4)):
        await _expect(
            fx.save_driver(wrong, mine.revision), Conflict, "tour_order_stale"
        )
    await _expect(
        fx.save_driver((a2, a1, a3, a4), mine.revision, actor=fx.admin),
        PermissionDenied,
        "delivery_board_forbidden",
    )


async def prove_tour_membership_changes(fx: _Fixture) -> None:
    """A newly assigned stop is last and ``new_for_driver``. A reassigned
    stop's positions are NULL and it is gone from the old tour. A cancelled
    stop closes up the ranks. A window change via delivery completion resets
    the positions."""

    a1, a2, a3, a4 = fx.a1, fx.a2, fx.a3, fx.a4
    newcomer = await fx.order("Tour A5", fx.first.id)
    await fx.assign(fx.anna_id, newcomer)
    own = await fx.own_tour()
    assert _ids(own) == [[a2, a1, a3, newcomer], [a4]], _ids(own)
    last = own.windows[0].stops[-1]
    assert last.new_for_driver and last.driver_rank == 4 and last.base_rank == 4
    assert not any(stop.new_for_driver for stop in own.windows[0].stops[:-1])
    revision_with_newcomer = own.revision

    # Reassigned: positions reset, gone from Anna's tour, ranks close up.
    await fx.assign(fx.ben_id, a1)
    row = await fx.positions(a1)
    assert row["base_position"] is None and row["driver_position"] is None
    assert row["driver_ordered_at"] is None
    own = await fx.own_tour()
    assert own.revision != revision_with_newcomer
    assert _ids(own) == [[a2, a3, newcomer], [a4]], _ids(own)
    assert [stop.effective_rank for stop in own.windows[0].stops] == [1, 2, 3]
    assert [stop.base_rank for stop in own.windows[0].stops] == [2, 1, 3]
    assert a1 in _flat(await fx.tour_of(fx.ben_id))

    # Cancelled: drops out, ranks close up.
    await fx.pool.execute("UPDATE commitment SET status='cancelled' WHERE id=$1", a2)
    own = await fx.own_tour()
    assert _ids(own) == [[a3, newcomer], [a4]], _ids(own)
    assert [stop.driver_rank for stop in own.windows[0].stops] == [1, 2]
    assert [stop.base_rank for stop in own.windows[0].stops] == [1, 2]

    # Window change: the delivery write shared by order edits and delivery
    # completion resets the positions (D14f). Completion refuses to move a
    # booked window today, so the proof calls that write directly.
    zone = (await AsyncpgDeliveryRepository(fx.pool).get(fx.action_id)).timezone

    async def move(window: DeliveryWindow) -> None:
        async with fx.pool.acquire() as connection:
            async with connection.transaction():
                await write_order_delivery(
                    connection,
                    commitment_id=a3,
                    window_id=window.id,
                    window_snapshot=window.snapshot(zone),
                    contact=None,
                )

    await move(fx.second)
    row = await fx.positions(a3)
    assert row["base_position"] is None and row["driver_position"] is None
    assert row["driver_ordered_at"] is None
    own = await fx.own_tour()
    assert _ids(own) == [[newcomer], [a4, a3]], _ids(own)
    assert own.windows[1].stops[-1].new_for_driver
    # Writing the same window again keeps the positions.
    await fx.save_driver((newcomer, a3, a4), own.revision)
    await move(fx.second)
    assert (await fx.positions(a3))["driver_position"] == 1
    print(
        "TOURS PASS: membership changes append as neu, reset on reassignment"
        " and window change, close up on cancellation"
    )


async def _prove_access_and_audit(fx: _Fixture) -> None:
    # foreign driver (driver role in another action) on my_tour: PermissionDenied delivery_board_forbidden
    await _expect(fx.my_tour(fx.foreign), PermissionDenied, "delivery_board_forbidden")
    await _expect(fx.my_tour(fx.admin), PermissionDenied, "delivery_board_forbidden")

    # my_tour writes one read audit row per window and day
    await fx.my_tour(on=fx.day)
    await fx.my_tour()
    audits = await fx.pool.fetch(
        "SELECT window_id, viewed_on FROM delivery_read_audit WHERE driver_user_id=$1",
        fx.anna_id,
    )
    assert {row["window_id"] for row in audits} == {fx.first.id, fx.second.id}, audits
    assert len(audits) == 2 and len({row["viewed_on"] for row in audits}) == 1
    await fx.my_tour(on=fx.other_day)
    assert (
        await fx.pool.fetchval(
            "SELECT count(*) FROM delivery_read_audit WHERE driver_user_id=$1",
            fx.anna_id,
        )
        == 3
    )
    # The manager's tour view is no driver read.
    await fx.day_tours()
    assert (
        await fx.pool.fetchval(
            "SELECT count(*) FROM delivery_read_audit WHERE driver_user_id=$1",
            fx.admin_id,
        )
        == 0
    )
    # A driver without stops gets no tour, and no audit rows.
    idle_id = await fx.driver("Tourfahrer Ohne")
    empty = await fx.my_tour(_principal(idle_id, fx.action_id, ActionRole.DRIVER))
    assert empty.tour is None and empty.days == ()
    assert not await fx.pool.fetchval(
        "SELECT count(*) FROM delivery_read_audit WHERE driver_user_id=$1", idle_id
    )


async def _prove_discard(fx: _Fixture) -> None:
    # discard_driver_order clears driver positions; empty driver write does the same
    current = await fx.tour_of(fx.anna_id)
    assert current.driver_ordered_at is not None
    await _expect(fx.discard(fx.anna), PermissionDenied, "delivery_management_required")
    discarded = await fx.discard()
    assert discarded.driver_ordered_at is None
    assert all(
        stop.driver_rank is None and not stop.new_for_driver
        for item in discarded.windows
        for stop in item.stops
    )
    stops = _flat(discarded)
    for commitment_id in stops:
        row = await fx.positions(commitment_id)
        assert row["driver_position"] is None and row["driver_ordered_at"] is None
    assert len(await fx.events("delivery.driver_order_discarded")) == 1
    # Discarding again changes nothing.
    await fx.discard()
    assert len(await fx.events("delivery.driver_order_discarded")) == 1
    again = await fx.save_driver(tuple(reversed(stops)), discarded.revision)
    assert again.driver_ordered_at is not None
    reset = await fx.save_driver((), again.revision)
    assert reset.driver_ordered_at is None and reset.revision == discarded.revision
    assert _ids(reset) == _ids(discarded)
    assert all(stop.drop.order_status is None for stop in reset.windows[0].stops)
    assert len(await fx.events("delivery.driver_order_discarded")) == 2


async def prove_driver_missed(fx: _Fixture) -> None:
    """Ruling 1: the assigned driver marks "Nicht angetroffen" in an open
    window and may withdraw it. Ruling 5: the closure gives every missed drop
    the "Nachliefern" follow-up; ``missed_at_closure`` only for drops open at
    closure. Ruling 6: reopening reverts only those; the driver's mark stays.
    A driver cannot reorder a closed window; a manager can."""

    pool, action_id, board = fx.pool, fx.action_id, fx.board
    absent = await fx.order("Tour Abwesend", fx.third.id)
    still_open = await fx.order("Tour Unerledigt", fx.third.id)
    await fx.assign(fx.anna_id, absent, still_open)

    async def state(commitment_id: UUID) -> asyncpg.Record:
        row = await pool.fetchrow(
            "SELECT state, missed_at_closure, revision FROM commitment_delivery"
            " WHERE commitment_id=$1",
            commitment_id,
        )
        assert row is not None
        return row

    async def task_status(commitment_id: UUID) -> str | None:
        value = await pool.fetchval(
            "SELECT task.status FROM task_delivery_follow_up AS follow_up"
            " JOIN task ON task.id = follow_up.task_id"
            " WHERE follow_up.commitment_id=$1",
            commitment_id,
        )
        return None if value is None else str(value)

    async def mark(
        actor: IdentityPrincipal,
        commitment_id: UUID,
        revision: int,
        *,
        delivered: bool = False,
        missed: bool = False,
    ) -> DeliveryDrop:
        return await board.set_state(
            actor,
            action_id,
            commitment_id,
            delivered=delivered,
            missed=missed,
            expected_revision=revision,
            request_id=REQUEST,
            occurred_at=fx.now,
        )

    # Flag off: "Nicht angetroffen" answers 404 for driver and manager;
    # delivered and back to open keep working.
    await pool.execute(
        "UPDATE feature_flag SET enabled=false, revision=revision+1"
        " WHERE key='delivery.tours'"
    )
    try:
        for actor in (fx.anna, fx.admin):
            await _expect(
                mark(actor, absent, (await state(absent))["revision"], missed=True),
                ResourceNotFound,
                "feature_flag_disabled",
            )
        delivered = await mark(
            fx.anna, absent, (await state(absent))["revision"], delivered=True
        )
        assert delivered.state is DropState.DELIVERED
        reopened = await mark(fx.anna, absent, delivered.revision)
        assert reopened.state is DropState.OPEN
    finally:
        await pool.execute(
            "UPDATE feature_flag SET enabled=true, revision=revision+1"
            " WHERE key='delivery.tours'"
        )

    # Ruling 1: driver-set missed in an open window, withdrawable; not by others.
    await _expect(
        mark(fx.ben, absent, (await state(absent))["revision"], missed=True),
        PermissionDenied,
        "delivery_not_assigned",
    )
    marked = await mark(fx.anna, absent, (await state(absent))["revision"], missed=True)
    assert marked.state is DropState.MISSED
    assert await task_status(absent) is None
    withdrawn = await mark(fx.anna, absent, marked.revision)
    assert withdrawn.state is DropState.OPEN
    marked = await mark(fx.anna, absent, withdrawn.revision, missed=True)
    assert marked.state is DropState.MISSED
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM audit_event WHERE entity_id=$1"
            " AND event_type='delivery.marked_missed'",
            absent,
        )
        == 2
    )

    # Ruling 5: the closure follows up every missed drop.
    missed_count = await board.close_window(
        fx.admin, action_id, fx.third.id, request_id=REQUEST, occurred_at=fx.now
    )
    assert missed_count == 3, missed_count  # absent, still_open, later
    closed_absent, closed_open = await state(absent), await state(still_open)
    assert closed_absent["state"] == "missed"
    assert not closed_absent["missed_at_closure"]
    assert closed_absent["revision"] == marked.revision
    assert closed_open["state"] == "missed" and closed_open["missed_at_closure"]
    assert await task_status(absent) == "open"
    assert await task_status(still_open) == "open"
    assert (
        await pool.fetchval(
            "SELECT missed_count FROM delivery_window_closure WHERE window_id=$1",
            fx.third.id,
        )
        == 3
    )
    await _expect(
        mark(fx.anna, absent, marked.revision, missed=True),
        Conflict,
        "delivery_window_closed",
    )

    # A driver cannot change the order of a closed window; the manager can.
    own = await fx.own_tour(fx.other_day)
    seen = _flat(own)
    assert sorted(seen) == sorted([fx.later, absent, still_open])
    await _expect(
        fx.save_driver(tuple(reversed(seen)), own.revision, on=fx.other_day),
        Conflict,
        "delivery_window_closed",
    )
    managed = await fx.save_base(tuple(reversed(seen)), own.revision, on=fx.other_day)
    assert _flat(managed) == list(reversed(seen))

    # Ruling 6: reopening reverts only drops missed at closure.
    assert (
        await board.reopen_window(
            fx.admin, action_id, fx.third.id, request_id=REQUEST, occurred_at=fx.now
        )
        == 2
    )
    reopened_absent, reopened_open = await state(absent), await state(still_open)
    assert reopened_absent["state"] == "missed", reopened_absent
    assert reopened_open["state"] is None and not reopened_open["missed_at_closure"]
    # No follow-ups in an open window: the next closure opens them again.
    assert await task_status(absent) == "done"
    assert await task_status(still_open) == "done"
    # The driver may still deliver in the reopened window.
    back = await mark(fx.anna, absent, reopened_absent["revision"], delivered=True)
    assert back.state is DropState.DELIVERED
    print(
        "TOURS PASS: missed 404 with the flag off (delivered still works),"
        " driver-set missed (Ruling 1), Nachliefern for every missed"
        " drop at closure (Ruling 5), reopen keeps the driver's mark (Ruling 6),"
        " closed window order kept for drivers"
    )
